"""Durable configurable batches. Completion order never determines scene order."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from ai_studio_pipeline import atomic_json, check_cancel, valid_image


class QueuedImageBatches:
    def __init__(self, generator, page, items, batch_size=6, timeout=300,
                 on_result=None, recover_only=False, retry_missing=False):
        self.generator, self.page = generator, page
        self.items = list(items)
        self.size = max(1, int(batch_size))
        self.timeout, self.on_result, self.recover_only = timeout, on_result, recover_only
        self.retry_missing=retry_missing
        self.path = Path(self.items[0][1]).parent / 'image_batches.json'
        self.state = {'version': 1, 'provider': generator.provider, 'requests': {}}
        if self.path.is_file():
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if state.get('version') != 1 or not isinstance(state.get('requests'), dict):
                raise RuntimeError('Image batch manifest is invalid; preserve it and restore the project before continuing.')
            self.state = state
        self.state.setdefault('project_id', uuid.uuid4().hex)
        self.results = [(False, 'Not generated: an earlier batch must complete first.')] * len(self.items)
        self.delivered = set()

    def save(self):
        self.state['batch_size'] = self.size
        self.state['profile'] = self.generator._profile_path.name
        atomic_json(self.path, self.state)

    def record(self, index):
        prompt, output = self.items[index]
        identity = json.dumps([self.generator.provider, self.generator.flow_project_url,
                               self.state['project_id'], Path(output).name, prompt], ensure_ascii=False)
        token = 'AS_SCENE_' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]
        records = self.state['requests']
        token=self.state.get('replacements',{}).get(token,token)
        if token not in records:
            records[token] = {
                'token': token, 'prompt': prompt, 'output': str(Path(output).resolve()),
                'scene_file': Path(output).name, 'status': 'pending',
                'submitted_prompt': prompt + '\nRequest tracking reference (metadata only): ' + token + '. Do not depict or write this reference in the image.',
            }
        record = records[token]
        record['output'] = str(Path(output).resolve())
        if record['status'] == 'complete' and not valid_image(output):
            record['status'] = 'submitted'  # recover by identity, do not submit again
        return record

    def deliver(self, index, ok, detail):
        self.results[index] = (ok, detail)
        if index not in self.delivered:
            if self.on_result:
                self.on_result(index, ok, detail)
            self.delivered.add(index)

    def harvest(self, group):
        pending = [record for index, record in group if record['status'] != 'complete']
        matches = self.generator._queued_image_results(self.page, pending)
        for index, record in group:
            if record['status'] == 'complete':
                self.deliver(index, True, self.items[index][1])
                continue
            match = matches.get(record['token'])
            if not match:
                continue
            # Save the verified identity before downloading: a failed download
            # or an interrupted job can recover that exact asset on resume.
            record['asset_id'] = match.get('asset_id', '')
            record['status'] = 'matched'
            self.save()
            if not self.generator._download_image(self.page, match['src'], record['output']) or not valid_image(record['output']):
                raise RuntimeError('Download failed for ' + record['scene_file'] + '; its matched asset identity was saved. Resume without regenerating.')
            record['status'] = 'complete'
            self.save()
            self.generator._log('Saved ' + record['scene_file'] + ' from its matched request identity.', 'success')
            self.deliver(index, True, self.items[index][1])

    def run(self):
        account = getattr(self.generator, 'browser_account', '')
        if self.state.get('browser_account', '') != account and self.state['requests']:
            raise RuntimeError('This image checkpoint belongs to another browser account. Resume using its original account to recover pending requests. Choose a new project for a different account.')
        self.state['browser_account'] = account
        records = [self.record(i) for i in range(len(self.items))]
        self.save()
        try:
            count = (len(records) + self.size - 1) // self.size
            for start in range(0, len(records), self.size):
                check_cancel(self.generator.cancel)
                group = list(enumerate(records[start:start+self.size], start))
                self.generator._log(f'Image batch {start // self.size + 1}/{count}: {len(group)} scene requests.')
                recovery_started=time.monotonic()
                self.harvest(group)  # recover existing results before spending another request
                self.generator._log(f'Checkpoint recovery check: {time.monotonic()-recovery_started:.1f}s.')
                awaiting=sum(r['status'] in ('sending','submitted','matched') for _,r in group)
                if awaiting:self.generator._log(f'Recovering {awaiting} previously submitted requests; no duplicate prompts will be sent.')
                error=self.generator._queued_error(self.page)
                if error:raise RuntimeError(error)
                if self.retry_missing and not self.recover_only:
                    if getattr(self.generator,'_queued_generation_busy',lambda p:True)(self.page):
                        raise RuntimeError('Flow is still generating or its busy state is unknown. Wait before explicitly regenerating missing thumbnails.')
                    for index,record in group:
                        if record['status']=='complete' or record['status']=='pending':continue
                        old=record['token'];new='AS_SCENE_'+uuid.uuid4().hex[:20]
                        replacement=dict(record,token=new,status='pending',replaces=old)
                        replacement.pop('asset_id',None)
                        replacement['submitted_prompt']=record['submitted_prompt'].replace(old,new)
                        self.state['requests'][new]=replacement
                        aliases=self.state.setdefault('replacements',{})
                        for original,current in list(aliases.items()):
                            if current==old:aliases[original]=new
                        aliases[old]=new
                        records[index]=replacement
                    group=[(index,records[index]) for index,_ in group]
                    self.save()
                if not self.recover_only:
                    queue_started=time.monotonic();queued=0
                    for index, record in group:
                        check_cancel(self.generator.cancel)
                        if record['status'] != 'pending':
                            continue  # already submitted/matched/completed: never submit twice
                        error = self.generator._queued_error(self.page)
                        if error:
                            self.harvest(group)
                            raise RuntimeError(error)
                        record['status'] = 'sending'
                        self.save()
                        ok, detail = self.generator._submit_queued_prompt(self.page, record['submitted_prompt'], self.timeout)
                        if not ok:
                            if detail.lower().startswith('not submitted:'):
                                record['status'] = 'pending'
                                self.save()
                                raise RuntimeError(detail)
                            raise RuntimeError(detail + '. Submission is unconfirmed; its scene identity is retained for recovery.')
                        record['status'] = 'submitted'
                        queued+=1
                        self.save()
                        self.generator._log('Queued ' + record['scene_file'] + '.')
                    if queued:self.generator._log(f'Queued {queued} requests in {time.monotonic()-queue_started:.1f}s; waiting for generated images.')
                deadline = time.monotonic() + self.timeout
                recovery_deadline=time.monotonic()+20 if awaiting and self.state.get('last_error') and not self.retry_missing else None
                next_report=time.monotonic()
                while any(record['status'] != 'complete' for index, record in group):
                    check_cancel(self.generator.cancel)
                    self.harvest(group)
                    if all(record['status'] == 'complete' for index, record in group):
                        break
                    error = self.generator._queued_error(self.page)
                    if error:
                        raise RuntimeError(error)
                    if (recovery_deadline is not None and time.monotonic()>=recovery_deadline
                        and getattr(self.generator,'_queued_generation_busy',lambda p:True)(self.page) is False):
                        raise RuntimeError('Previously submitted images still have no matching output and Flow is idle. For thumbnails, use Regenerate Missing Thumbnails to explicitly replace the unresolved request. Saved images and old request identities retained.')
                    if self.recover_only or time.monotonic() >= deadline:
                        raise RuntimeError('Not all images in this batch could be matched. Pending requests are retained; the next batch was not started.')
                    if time.monotonic()>=next_report:
                        remaining=sum(r['status']!='complete' for _,r in group)
                        self.generator._log(f'Waiting for {remaining} matching image outputs; {max(0,deadline-time.monotonic()):.0f}s remain in this collection attempt. Submitted identities retained.')
                        next_report=time.monotonic()+15
                    time.sleep(.5)
                self.generator._log(f'Image batch {start // self.size + 1}/{count} complete; all scene images matched and saved.', 'success')
            self.state.pop('last_error', None)
            self.state.pop('pause_reason', None)
            self.save()
        except Exception as error:
            from ai_studio_pipeline import Cancelled
            self.state['last_error'] = str(error)
            self.state['pause_reason'] = 'account_limit' if 'Account limit reached:' in str(error) else 'recovery_required'
            self.save()
            if isinstance(error, Cancelled):
                raise
            self.generator._log('Image batches paused: ' + str(error), 'error')
            for index in range(len(self.items)):
                if index not in self.delivered:
                    self.deliver(index, False, str(error))
        return self.results
