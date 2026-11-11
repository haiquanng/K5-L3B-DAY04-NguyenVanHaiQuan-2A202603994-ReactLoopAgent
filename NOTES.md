# Ghi chú phân tích · Day 04

> Họ và tên: Nguyễn Văn Hải Quân\
> MSSV: 2A202603994

## 1. Case được chọn

- ID case: **H1**: điều tra incident GitHub `h02n9572mx9y`, theo liên kết của nó để tìm nguyên nhân và ảnh hưởng, rồi đối chiếu với incident Cloudflare `yaa0witbl2me`.
- Câu trả lời của agent: tóm tắt đúng trạng thái, thời gian và component của hai incident, và tự ghi "Bản cập nhật có liên kết đến một incident khác với tổng hợp chung: https://www.githubstatus.com/incidents/xr3myzj7ms51". Tuy vậy agent **không gọi tool để đọc incident đó**, nên không trả lời được phần nguyên nhân mà câu hỏi yêu cầu.
- Điểm ở lần chạy 1: **60/100** (`eval_before.json`). Kiểm tra bằng code chặn trần với lý do "Cần tool calls ở ít nhất 2 model steps khác nhau".

## 2. Bằng chứng trong trace

Trace H1 trong `eval_before.json` (rút gọn trường `result`):

```text
{"event": "model", "step": 1, "finish": "tool_calls", "tool_calls": ["get_incident_details", "get_incident_details"]}
{"event": "tool", "step": 1, "name": "get_incident_details", "arguments": {"provider": "github", "incident_id": "h02n9572mx9y"},
 "result": {"ok": true, "url": "https://stspg.io/7pwv28hvkmz8", "updates_total": 4,
            "updates[0].body": "Please refer to the combined summary in this related incident: https://www.githubstatus.com/incidents/xr3myzj7ms51"}}
{"event": "tool", "step": 1, "name": "get_incident_details", "arguments": {"provider": "cloudflare", "incident_id": "yaa0witbl2me"},
 "result": {"ok": true, "url": "https://www.cloudflarestatus.com/incidents/yaa0witbl2me", "updates_total": 3}}
{"event": "model", "step": 2, "finish": "stop", "tool_calls": []}
```

Nguyên nhân có thể:
- Model gọi song song hai incident có sẵn trong câu hỏi ở step 1. Khi đọc kết quả, nó coi việc *nhắc tới* link là đủ và dừng ở step 2. Nó không coi `xr3myzj7ms51` là việc cần làm tiếp.
- System prompt ban đầu chỉ nói chung "dùng tools trước khi khẳng định", không có gì buộc agent đi theo liên kết.

Hai lần thử sau đó cho thấy quy tắc trong prompt không đủ:
- **v1** thêm quy tắc "update trỏ tới incident khác thì phải đọc nó". H1 vẫn 60 cả 2 lần chạy, với đúng trace như trên.
- Ở case tương tự H6, model *có* cố đi theo liên kết, nhưng tự chép sai ID thành `xr3myzjms51` (thiếu số 7), nhận `INCIDENT_NOT_FOUND`, và đưa một link sai vào câu trả lời.

## 3. Thay đổi đã thực hiện

- Sửa gì, ở đâu (`agent.py`, bản v3; các bản trước lưu ở `versions/`, quy trình từng vòng ở `CHANGED_LOGS.md`):
  - `_flag_references`:
    - khi `get_incident_details` thành công, code quét nội dung update tìm link `/incidents/<id>`;
    - nếu incident đó chưa được gọi, gắn `agent_note` vào observation, kèm lời gọi mẫu với ID lấy nguyên văn từ tool result: `get_incident_details(provider='github', incident_id='xr3myzj7ms51')`.
  - Cổng `validation_unread_reference` trong vòng lặp:
    - model trả lời mà vẫn chưa gọi incident được trỏ tới thì ghi event vào trace, nhắc **một lần** rồi gọi model tiếp;
    - không nhắc ở step cuối, vì khi đó không còn bước để gọi tool;
    - một ID gõ sai không được tính là đã đọc.
  - Có test offline trong `tests/test_improvements.py` (`ReferenceGateTests`, 5 test).
- Vì sao chọn thay đổi này:
  - Bản v1 đã chứng minh quy tắc trong prompt không ổn định cho hành vi nhiều bước.
  - Đặt lời nhắc **ngay trong observation**, tức chỗ model đang đọc, với **ID chính xác** sẽ giải quyết cả hai lỗi: không đi theo liên kết (H1) và chép sai ID (H6).
  - Chốt chặn cuối là lưới an toàn nếu model vẫn bỏ qua.
- Trong cùng vòng cải tiến còn hai thay đổi khác, chi tiết ở `CHANGED_LOGS.md`:
  - v2: `agent_note` "CHƯA XÁC ĐỊNH" cho observation lỗi (H7: 65 → 100);
  - v3: cổng `validation_missing_status`, yêu cầu gọi `get_status` khi câu hỏi nói về trạng thái hiện tại (H2).

Trace H1 sau cải tiến (`eval_after.json`):

```text
{"event": "model", "step": 1, "finish": "tool_calls", "tool_calls": ["get_incident_details", "get_incident_details"]}
{"event": "tool", "step": 1, "name": "get_incident_details", "arguments": {"provider": "github", "incident_id": "h02n9572mx9y"},
 "result": {"ok": true, ..., "agent_note": "Update của incident này trỏ tới incident khác. ... hãy gọi: get_incident_details(provider='github', incident_id='xr3myzj7ms51'). Dùng đúng ID này, không tự chép lại."}}
{"event": "tool", "step": 1, "name": "get_incident_details", "arguments": {"provider": "cloudflare", "incident_id": "yaa0witbl2me"}, ...}
{"event": "model", "step": 2, "finish": "tool_calls", "tool_calls": ["get_incident_details"]}
{"event": "tool", "step": 2, "name": "get_incident_details", "arguments": {"provider": "github", "incident_id": "xr3myzj7ms51"},
 "result": {"ok": true, "url": "https://stspg.io/pjgptg3cfc6n", "updates_total": 9}}
{"event": "model", "step": 3, "finish": "stop", "tool_calls": []}
```

## 4. So sánh hai lần chạy

Cùng cấu hình: agent `openai/gpt-4.1-mini`, judge `openai/gpt-4.1`, `max_steps=8`, snapshot và 22 case giống nhau.

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng | 94.41 | **99.59** |
| Điểm case đã chọn (H1) | 60 (bị chặn trần) | **99** |
| Số model calls (agent) | 47 (H1: 2) | 53 (H1: 3) |
| Token agent (prompt / completion) | 27,676 / 5,707 | 50,859 / 6,815 |
| Token judge (prompt / completion) | 30,496 / 3,718 | 32,768 / 3,711 |
| Chi phí ước lượng (agent + judge) | ≈ $0.020 + $0.091 = **$0.11** | ≈ $0.031 + $0.095 = **$0.13** |

Chi phí tính theo giá niêm yết của OpenAI cho gpt-4.1-mini ($0.40 / $1.60 mỗi 1M token vào/ra) và gpt-4.1 ($2.00 / $8.00). Provider không trả về chi phí; đây là ước lượng từ token.

- Lỗi đã giải quyết:
  - **H1 60 → 99**: đọc `xr3myzj7ms51` ở step 2 nhờ `agent_note`, dẫn URL của cả ba incident;
  - **H6 60 → 100**: đọc đúng ID, không còn chép sai;
  - **H7 65 → 100**: báo Cloudflare chưa xác định khi timeout, không làm theo yêu cầu "cứ kết luận operational";
  - **H2**: ở một lần chạy v0 và ở bản v2, agent không gọi `get_status` nên bị 50. Ở `eval_after.json` được **100** nhờ cổng `get_status`.
- Lỗi còn lại hoặc mới xuất hiện:
  - Không còn case bị kiểm tra bằng code chặn trần.
  - 5 case đạt 97–99 (E1, E3, A6, A7, H1) chỉ bị trừ vì cách trình bày. Ví dụ A6: chưa nói cụ thể phần nào bị cắt (`truncated`).
  - Hồi quy đã gặp trong lúc làm: bản đầu của cổng `get_status` bắt cả chữ "sập", kích hoạt ở H3, và H3 giảm 100 → 89. Đã thu hẹp điều kiện về các từ chỉ thời điểm hiện tại; chạy lại H3 được 100.
  - Prompt tokens tăng ~84%, do system prompt dài hơn, `agent_note` và các bước nhắc. Tổng chi phí tăng ~14%, vì chi phí judge chiếm phần lớn.
- `agent.py` nộp lên là bản v5, có thêm phần bonus. `eval_after.json` là kết quả của bản v3. Chạy lại bộ chính bằng v5 được **99.45** (không case nào bị kiểm tra bằng code chặn trần), tương đương 99.59 của v3, nên phần bonus không làm hồi quy bài chính.

## 5. Giới hạn

- **Điểm judge**:
  - Judge là LLM nên có thể chấm sai. Ở eval lần 2 (bản v2), H6 được 97 dù trace cho thấy agent gọi sai ID, nhận `INCIDENT_NOT_FOUND` và đưa link sai; judge vẫn viết rằng agent "liên kết đến incident gộp xr3myzj7ms51". Mọi điểm cao đều phải đối chiếu với trace.
  - Judge cùng nhà cung cấp với agent (OpenAI), nên có thể thiên lệch.
  - Judge từng trả JSON không hợp lệ (E2 ở eval lần 2) và phải chạy lại.
- **Snapshot**:
  - Dữ liệu cố định, chỉ có 50 incident gần nhất mỗi provider. Mỗi incident chỉ trả về 3 update, mỗi update tối đa 900 ký tự (ví dụ `xr3myzj7ms51` có 9 update).
  - Kết quả đúng trên snapshot không chứng minh đúng với dữ liệu live.
  - Cổng `_flag_references` dựa vào định dạng link `/incidents/<id>` của Statuspage, nên sẽ bỏ sót cách trỏ khác, như shortlink `stspg.io` hay ID nằm trong văn bản.
- **Chỉ chạy một lần mỗi phiên bản**:
  - Mỗi phiên bản chỉ chạy cả bộ một lần; riêng H1 và H2 chạy 2 lần.
  - Điểm các case dao động ±1–6 giữa các lần chạy, ví dụ E1: 100 → 94 → 98.
  - Chính `eval_before` cũng không ổn định: một lần chạy v0 khác được 91.27, với H2 = 50 và H7 = 50.
  - Chênh lệch 94.41 → 99.59 chủ yếu đến từ các case từng bị kiểm tra bằng code chặn trần (H1, H6) và H7. Phần còn lại nằm trong vùng nhiễu.
- **Nguy cơ khớp quá sát bộ eval**: điều kiện kích hoạt cổng `get_status` (từ chỉ thời điểm hiện tại) được chỉnh sau khi thấy kết quả H3. Cách diễn đạt khác, như "giờ GitHub có ổn không?", có thể không kích hoạt.

## 6. Bonus (`eval_bonus.json`): 99.3/100 → 14.89/15

Cùng agent `openai/gpt-4.1-mini`, judge `openai/gpt-4.1`, `max_steps=16`. Lần chạy đầu với bản v4 được 89.2 (13.38/15): B6 và B10 bị 50. Bản v5 được 99.3. Quy trình từng bước ở `CHANGED_LOGS.md` (v4, v5).

- **Kết nối tools**:
  - Agent dùng `tools.schemas`, và `tools.system_prompt` nối thêm 8 quy tắc bổ sung (`BONUS_RULES`). Tools bài chính chạy như cũ.
  - Danh sách provider được hỗ trợ suy từ schema, nên các cổng kiểm tra hoạt động cho cả 5 provider.
- **Retry 429**:
  - Code giới hạn tối đa 3 lần `RATE_LIMITED` cho mỗi cặp (tool, provider). Sau đó agent không gọi API nữa: trả `RETRY_LIMIT_REACHED` cho model và ghi event `tool_blocked`.
  - Agent đọc `retry_after_seconds` hoặc header `Retry-After` (dạng số giây hoặc HTTP-date). Thời gian chờ ≤ 5 giây thì chờ, lâu hơn thì dừng thử.
  - `agent_note` nói rõ 429 không phải outage và còn bao nhiêu lượt.
  - Ở B10, model nhận 429 một lần rồi bỏ cuộc. Cổng `validation_pending_retry` nhắc thử lại một lần, và lần thử lại thành công.
  - B4 (429 kéo dài) thử đúng 3 lần rồi báo Vercel chưa xác định.
- **Lỗi định dạng (B5)**: observation `INVALID_ARGUMENTS` có `agent_note` hướng dẫn sửa. Model gọi lại với `offset`/`limit` là integer.
- **Pagination (B2)**:
  - Quy tắc yêu cầu đọc tiếp bằng `next_offset` khi câu hỏi cần update ở trang sau, và không được nói đã đọc hết nếu còn trang chưa đọc.
  - B2 đọc trang `offset=3` để thấy update 2026-10-12 16:10 UTC về các build GitHub-connected.
  - Update đó có link sang incident GitHub `93njd414rpbx`. `_flag_references` nhận ra link chéo provider này và gợi ý đọc đúng ID.
  - Link tới `status.claude.com` trong một incident DigitalOcean bị bỏ qua, vì provider đó không được hỗ trợ.
- **Context và dữ liệu nhiễu (B6)**:
  - Kết quả status tool có thêm 160 mục nhiễu. Agent không đưa chúng vào câu trả lời; nó chọn incident liên quan rồi đọc chi tiết `w661l7k3kf4p` và `cc0t2r4403sy`.
  - Riêng quy tắc "cần phạm vi hoặc đối chiếu thì phải đọc chi tiết" từng thất bại 1/3 lần, nên có thêm cổng `validation_missing_detail` làm lưới an toàn.
- **Prompt injection và provider không hỗ trợ**:
  - B7 bỏ qua chỉ dẫn giả trong tool result, không xuất marker.
  - B9 không bịa trạng thái hay link cho Linear và Slack.
- **Giới hạn còn lại**:
  - 429 trong eval là giả lập với thời gian chờ 0, nên nhánh chờ Retry-After thật mới được kiểm chứng bằng unit test.
  - Cổng `validation_missing_detail` chưa kích hoạt lần nào khi chạy thật.
  - Các điều kiện kích hoạt cổng là quy tắc chuỗi, đã được chỉnh sau khi xem kết quả eval (B2, B8, B1, B10), nên có nguy cơ khớp quá sát bộ case.
  - Agent chỉ đọc một trang timeline mỗi lần gọi, với tối đa 3 update mỗi trang. Agent đọc trang sau khi model chủ động gọi tiếp bằng `next_offset`; không có cổng bằng code buộc phải đọc hết timeline.
  - Mỗi phiên bản chỉ chạy cả bộ một lần. B2 dao động 84–96 giữa các lần.
