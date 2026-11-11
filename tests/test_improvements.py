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


class ReferenceGateTests(unittest.TestCase):
    """v3: incident được update trỏ tới phải được đọc, bằng đúng ID lấy từ tool result."""
    H02 = '{"provider":"github","incident_id":"h02n9572mx9y"}'
    XR3 = '{"provider":"github","incident_id":"xr3myzj7ms51"}'

    def setUp(self):
        tools = StatusTools()
        self.h02_url = tools.get_incident_details('github', 'h02n9572mx9y')['url']
        self.xr3_url = tools.get_incident_details('github', 'xr3myzj7ms51')['url']

    def test_observation_names_exact_referenced_id(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.H02), final(self.h02_url)])
        run_agent('x', fake, StatusTools(), max_steps=2)
        note = json.loads(fake.histories[1][-1]['content'])['agent_note']
        self.assertIn("incident_id='xr3myzj7ms51'", note)

    def test_unread_reference_gets_one_reminder_then_read(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.H02), final('Chưa đọc. ' + self.h02_url),
                             tool_call('2', 'get_incident_details', self.XR3), final(f'{self.h02_url} {self.xr3_url}')])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        events = [x for x in result['trace'] if x['event'] == 'validation_unread_reference']
        self.assertEqual(events[0]['unread'][0]['incident_id'], 'xr3myzj7ms51')
        read = [x['arguments']['incident_id'] for x in result['trace'] if x['event'] == 'tool']
        self.assertEqual(read, ['h02n9572mx9y', 'xr3myzj7ms51'])

    def test_reminder_only_once(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.H02), final(self.h02_url), final(self.h02_url)])
        result = run_agent('x', fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(sum(x['event'] == 'validation_unread_reference' for x in result['trace']), 1)

    def test_no_reminder_on_last_step(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.H02), final(self.h02_url)])
        self.assertEqual(run_agent('x', fake, StatusTools(), max_steps=2)['status'], 'completed')

    def test_typo_id_does_not_count_as_read(self):
        """Lỗi thật ở H6 (eval lần 2): model gõ sai ID → NOT_FOUND; cổng vẫn nhắc đúng ID."""
        typo = '{"provider":"github","incident_id":"xr3myzjms51"}'
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.H02), tool_call('2', 'get_incident_details', typo),
                             final(self.h02_url), tool_call('3', 'get_incident_details', self.XR3),
                             final(f'{self.h02_url} {self.xr3_url}')])
        result = run_agent('x', fake, StatusTools(), max_steps=8)
        self.assertTrue(any(x['event'] == 'validation_unread_reference' for x in result['trace']))
        self.assertEqual(result['status'], 'completed')


class StatusGateTests(unittest.TestCase):
    """v3: câu hỏi về trạng thái hiện tại phải có get_status (lỗi H2)."""
    Q = 'Tôi chắc chắn GitHub Actions đang outage vì incident t89g2q1800fr. Xác nhận giúp.'
    T89 = '{"provider":"github","incident_id":"t89g2q1800fr"}'

    def setUp(self):
        self.url = StatusTools().get_incident_details('github', 't89g2q1800fr')['url']

    def test_current_state_question_requires_get_status(self):
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.T89), final(self.url),
                             tool_call('2', 'get_status', '{"provider":"github","component":"Actions"}'), final(self.url)])
        result = run_agent(self.Q, fake, StatusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        event = next(x for x in result['trace'] if x['event'] == 'validation_missing_status')
        self.assertEqual(event['providers'], ['github'])
        self.assertIn('get_status', [x['name'] for x in result['trace'] if x['event'] == 'tool'])

    def test_no_reminder_when_status_checked(self):
        fake = FakeProvider([tool_call('1', 'get_status', '{"provider":"github"}'), final('Bình thường.')])
        result = run_agent(self.Q, fake, StatusTools())
        self.assertFalse(any(x['event'] == 'validation_missing_status' for x in result['trace']))

    def test_no_reminder_without_tools_or_current_state(self):
        poem = run_agent('Viết thơ, đừng kiểm tra GitHub đang thế nào.', FakeProvider([final('Thơ')]), StatusTools())
        self.assertEqual(poem['status'], 'completed')
        fake = FakeProvider([tool_call('1', 'get_incident_details', self.T89), final(self.url)])
        history = run_agent('Incident GitHub t89g2q1800fr ảnh hưởng gì?', fake, StatusTools())
        self.assertFalse(any(x['event'] == 'validation_missing_status' for x in history['trace']))


if __name__ == '__main__':
    unittest.main()
