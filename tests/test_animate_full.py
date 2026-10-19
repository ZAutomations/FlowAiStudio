import unittest
from unittest.mock import Mock
from contextlib import contextmanager
from pathlib import Path
from PIL import Image
class FullAnimateTests(unittest.TestCase):

    def fake_agent(self, prepared, submitted):
        parent = self

        class Agent:

            def __init__(self, *args, **kwargs):
                self._flow_asset_prompts = {}

            @contextmanager
            def _session(self, **kwargs):
                yield None

            def _batch_page(self, ctx):
                page = Mock()
                element = Mock()
                element.first = element
                element.inner_text.side_effect = lambda: prepared[-1]
                element.get_attribute.return_value = 'true'
                element.is_enabled.return_value = True
                element.click.side_effect = lambda **kwargs: submitted.append(prepared[-1])
                page.locator.return_value = element
                return page

            def collect(self, records, save, on_media):
                for record in records:
                    path = Path(record['output'])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if record['kind'] == 'image':
                        Image.new('RGB', (32, 32), 'red').save(path)
                    else:
                        path.write_bytes(record['key'].encode())
                    record['status'] = 'complete'
                    save()
                    on_media(record)
        return Agent
