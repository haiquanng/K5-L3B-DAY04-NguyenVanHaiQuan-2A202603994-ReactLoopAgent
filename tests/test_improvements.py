"""Tests offline cho các cải tiến sau baseline (Bài 4). Không gọi LLM API."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_dang_about_incident_or_apps_does_not_trigger(self):
        # v5: B2 hỏi "sự cố đó đang xảy ra" (về incident), B8 nói "ứng dụng đang chạy".
        from agent import CURRENT_STATE_RE
        self.assertIsNone(CURRENT_STATE_RE.search('Có thể xác nhận sự cố đó đang xảy ra không?'))
        self.assertIsNone(CURRENT_STATE_RE.search('ảnh hưởng ứng dụng đang chạy và build/deploy'))
        for q in ('GitHub Actions đang outage', 'Actions đang thế nào', 'GitHub hiện có sự cố không'):
            self.assertIsNotNone(CURRENT_STATE_RE.search(q), q)


class RateLimitTests(unittest.TestCase):
    """v3: giới hạn retry 429 và đọc Retry-After (tools bonus)."""

    def vercel_calls(self, n):
        return [tool_call(str(i), 'get_vercel_status', '{}') for i in range(n)]

    def test_persistent_429_stops_after_three_attempts(self):
        from bonus.tools import BonusTools
        fake = FakeProvider(self.vercel_calls(5) + [final('Vercel chưa xác định.')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=8)
        self.assertEqual(result['status'], 'completed')
        executed = [x for x in result['trace'] if x['event'] == 'tool' and x['name'] == 'get_vercel_status']
        blocked = [x for x in result['trace'] if x['event'] == 'tool_blocked']
        self.assertEqual(len(executed), 3)
        self.assertEqual(len(blocked), 2)
        self.assertIn(UNAVAILABLE, json.loads(fake.histories[3][-1]['content'])['agent_note'])

    def test_transient_429_then_success(self):
        from bonus.tools import BonusTools
        fake = FakeProvider(self.vercel_calls(2) + [final()])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_once'), max_steps=5)
        first = json.loads(fake.histories[1][-1]['content'])
        self.assertIn('KHÔNG phải outage', first['agent_note'])
        self.assertEqual(json.loads(fake.histories[2][-1]['content'])['provider'], 'vercel')
        self.assertEqual(result['status'], 'completed')

    def make_tools(self, retry_after):
        class Tools:
            schemas, system_prompt = [], 'bonus'
            def execute(self, name, args):
                return {'ok': False, 'error': 'RATE_LIMITED', 'http_status': 429, 'retriable': True, 'retry_after': retry_after}
        return Tools()

    def test_short_retry_after_waits(self):
        with patch('agent.time.sleep') as sleep:
            run_agent('x', FakeProvider(self.vercel_calls(1) + [final()]), self.make_tools('2'))
        sleep.assert_called_once_with(2.0)

    def test_long_retry_after_stops_without_waiting(self):
        with patch('agent.time.sleep') as sleep:
            result = run_agent('x', FakeProvider(self.vercel_calls(2) + [final()]), self.make_tools('120'))
        sleep.assert_not_called()
        self.assertEqual(sum(x['event'] == 'tool_blocked' for x in result['trace']), 1)

    def test_bonus_prompt_gets_extra_rules(self):
        fake = FakeProvider([final()])
        run_agent('x', fake, self.make_tools('0'))
        self.assertTrue(fake.histories[0][0]['content'].startswith('bonus'))
        self.assertIn('Quy tắc bổ sung', fake.histories[0][0]['content'])
        self.assertIn('429', fake.histories[0][0]['content'])


class BonusGateTests(unittest.TestCase):
    """v4: các cổng của v3 chạy đúng với 5 provider của bộ bonus."""

    def test_unknown_host_link_is_ignored(self):
        # Incident DigitalOcean lrrw084g3whn có link tới status.claude.com (provider không được hỗ trợ).
        from bonus.tools import BonusTools
        args = '{"provider":"digitalocean","incident_id":"lrrw084g3whn","offset":0,"limit":3}'
        url = BonusTools().get_incident_details('digitalocean', 'lrrw084g3whn')['url']
        fake = FakeProvider([tool_call('1', 'get_incident_details', args), final(url)])
        result = run_agent('x', fake, BonusTools(), max_steps=4)
        self.assertNotIn('agent_note', json.loads(fake.histories[1][-1]['content']))
        self.assertFalse(any(x['event'] == 'validation_unread_reference' for x in result['trace']))

    def test_cross_provider_link_is_flagged(self):
        # Trang 2 timeline Vercel sps6n39gm4sg trỏ tới incident GitHub 93njd414rpbx.
        from bonus.tools import BonusTools
        args = '{"provider":"vercel","incident_id":"sps6n39gm4sg","offset":3,"limit":3}'
        fake = FakeProvider([tool_call('1', 'get_incident_details', args), final('x')])
        run_agent('x', fake, BonusTools(), max_steps=2)
        note = json.loads(fake.histories[1][-1]['content'])['agent_note']
        self.assertIn("provider='github', incident_id='93njd414rpbx'", note)

    def test_status_gate_names_bonus_tool(self):
        from bonus.tools import BonusTools
        args = '{"provider":"npm","incident_id":"cc0t2r4403sy"}'
        url = BonusTools().get_incident_details('npm', 'cc0t2r4403sy')['url']
        fake = FakeProvider([tool_call('1', 'get_incident_details', args), final(url),
                             tool_call('2', 'get_npm_status', '{}'), final(url)])
        result = run_agent('npm hiện có ổn không?', fake, BonusTools(), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('get_npm_status()', fake.histories[2][-1]['content'])


class PendingRetryTests(unittest.TestCase):
    """v5: còn lượt thử sau 429 thì nhắc thử lại một lần trước khi trả lời (lỗi B10)."""

    def vercel(self, i):
        return tool_call(str(i), 'get_vercel_status', '{}')

    def events(self, result):
        return [x for x in result['trace'] if x['event'] == 'validation_pending_retry']

    def test_single_429_gets_retry_reminder(self):
        from bonus.tools import BonusTools
        fake = FakeProvider([self.vercel(1), final('Vercel chưa xác định.'), self.vercel(2), final('Vercel bình thường.')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_once'), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.events(result)), 1)
        calls = [x for x in result['trace'] if x['event'] == 'tool' and x['name'] == 'get_vercel_status']
        self.assertEqual([x['result'].get('error') for x in calls], ['RATE_LIMITED', None])

    def test_reminder_only_once_when_still_limited(self):
        from bonus.tools import BonusTools
        fake = FakeProvider([self.vercel(1), final('a'), self.vercel(2), final('Vercel chưa xác định.')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(self.events(result)), 1)

    def test_no_reminder_after_attempts_exhausted(self):
        from bonus.tools import BonusTools
        fake = FakeProvider([self.vercel(1), self.vercel(2), self.vercel(3), final('Vercel chưa xác định.')])
        result = run_agent('x', fake, BonusTools(scenario='rate_limit_always'), max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.events(result), [])


class DetailGateTests(unittest.TestCase):
    """v5: câu hỏi cần phạm vi/đối chiếu incident thì phải đọc chi tiết (lỗi B6)."""
    Q = 'Kiểm tra Vercel Builds và npm package publishing, đối chiếu incident mới nhất: phạm vi, timestamp, nguồn.'

    def status_calls(self):
        first = tool_call('a', 'get_vercel_status', '{"component":"Builds"}')
        second = tool_call('b', 'get_npm_status', '{"component":"publish"}')
        first['calls'] += second['calls']
        first['message']['tool_calls'] += second['message']['tool_calls']
        return first

    def test_compare_question_without_detail_gets_candidates(self):
        from bonus.tools import BonusTools
        fake = FakeProvider([self.status_calls(), final('Chỉ dựa vào danh sách.'), final('x')])
        result = run_agent(self.Q, fake, BonusTools(), max_steps=3)
        event = next(x for x in result['trace'] if x['event'] == 'validation_missing_detail')
        self.assertEqual(event['candidates'], {'vercel': 'w661l7k3kf4p', 'npm': 'cc0t2r4403sy'})
        self.assertIn("incident_id='w661l7k3kf4p'", fake.histories[2][-1]['content'])

    def test_no_reminder_for_negated_cause_or_after_detail(self):
        from bonus.tools import BonusTools
        q = 'Tổng hợp status Vercel và npm. Đừng suy ra nguyên nhân liên quan giữa các bên.'
        result = run_agent(q, FakeProvider([self.status_calls(), final('ok')]), BonusTools())
        self.assertFalse(any(x['event'] == 'validation_missing_detail' for x in result['trace']))
        url = BonusTools().get_incident_details('npm', 'cc0t2r4403sy')['url']
        fake = FakeProvider([self.status_calls(), tool_call('c', 'get_incident_details', '{"provider":"npm","incident_id":"cc0t2r4403sy"}'), final(url)])
        result = run_agent(self.Q, fake, BonusTools())
        self.assertFalse(any(x['event'] == 'validation_missing_detail' for x in result['trace']))


if __name__ == '__main__':
    unittest.main()
