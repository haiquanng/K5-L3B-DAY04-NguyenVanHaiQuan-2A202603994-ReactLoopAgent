"""Tests offline cho các cải tiến sau baseline (Bài 4). Không gọi LLM API."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'evals'))
from agent import run_agent, UNAVAILABLE
from scenarios import ScenarioTools
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call, final

GH = '{"provider":"github","incident_id":"xr3myzj7ms51"}'
CF = '{"provider":"cloudflare","incident_id":"yaa0witbl2me"}'


def two_calls(a, b):
    first = tool_call('a', 'get_incident_details', a)
    second = tool_call('b', 'get_incident_details', b)
    first['calls'] += second['calls']
    first['message']['tool_calls'] += second['message']['tool_calls']
    return first


class SourceGateTests(unittest.TestCase):
    def test_each_provider_needs_its_own_source(self):
        gh_url = StatusTools().get_incident_details('github', 'xr3myzj7ms51')['url']
        cf_url = StatusTools().get_incident_details('cloudflare', 'yaa0witbl2me')['url']
        fake = FakeProvider([two_calls(GH, CF), final('Chỉ có ' + gh_url), final(f'{gh_url} và {cf_url}')])
        result = run_agent('So sánh', fake, StatusTools(), max_steps=4)
        self.assertEqual(result['status'], 'completed')
        events = [x for x in result['trace'] if x['event'] == 'validation_missing_source']
        self.assertEqual(len(events), 1)
        self.assertEqual(list(events[0]['missing']), ['cloudflare'])

    def test_canonical_incident_url_is_accepted(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', GH),
                             final('Nguồn: https://www.githubstatus.com/incidents/xr3myzj7ms51.')])
        result = run_agent('x', fake, StatusTools())
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(any(x['event'] == 'validation_missing_source' for x in result['trace']))

    def test_status_only_does_not_require_incident_url(self):
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"github"}'), final('GitHub bình thường.')])
        self.assertEqual(run_agent('x', fake, StatusTools())['status'], 'completed')


class ErrorNoteTests(unittest.TestCase):
    def test_timeout_is_marked_unavailable(self):
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"cloudflare"}'), final('Cloudflare chưa xác định.')])
        run_agent('x', fake, ScenarioTools('cloudflare_timeout'))
        sent = json.loads(fake.histories[1][-1]['content'])
        self.assertEqual(sent['error'], 'TimeoutError')
        self.assertIn(UNAVAILABLE, sent['agent_note'])
        self.assertIn('cloudflare', sent['agent_note'])

    def test_not_found_does_not_confirm_or_deny(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', '{"provider":"cloudflare","incident_id":"fake"}'), final('Không tìm thấy.')])
        run_agent('x', fake, StatusTools())
        note = json.loads(fake.histories[1][-1]['content'])['agent_note']
        self.assertIn('KHÔNG xác nhận', note)

    def test_successful_result_has_no_note(self):
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"github"}'), final()])
        run_agent('x', fake, StatusTools())
        self.assertNotIn('agent_note', json.loads(fake.histories[1][-1]['content']))

    def test_tool_result_dict_is_not_mutated(self):
        class Tools(StatusTools):
            last = None
            def execute(self, name, args):
                Tools.last = {'ok': False, 'error': 'TimeoutError', 'message': 't'}
                return Tools.last
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"github"}'), final()])
        run_agent('x', fake, Tools())
        self.assertNotIn('agent_note', Tools.last)


if __name__ == '__main__':
    unittest.main()
