# CHANGED_LOGS — Quy trình cải thiện agent

Nhật ký từng vòng: sửa gì, vì sao, kết quả đo được. Cấu hình eval giữ nguyên giữa các vòng: agent `openai/gpt-4.1-mini`, judge `openai/gpt-4.1`, `max_steps=8`, snapshot cố định.

## v0 — Baseline (Bài 1 + 2)

**Thay đổi** ([agent.py](agent.py)): viết `run_agent`
- Vòng lặp tối đa `max_steps` lần gọi model (mỗi model call = 1 step).
- Append nguyên `message` của assistant trước tool results; mỗi call có đúng một tool message với `tool_call_id` tương ứng (xử lý mọi call trong một response).
- JSON arguments lỗi hoặc không phải object → trả `INVALID_ARGUMENTS` cho model, không crash.
- Tool ném exception ngoài dự kiến → đưa vào observation `{ok: false, ...}`.
- `finish == 'length'` hoặc lý do dừng lạ → `status: error`; provider lỗi → `status: error` kèm trace `provider_error`; hết bước → `max_steps`.
- Trace gồm event `model`, `tool` (đúng dạng `{event, step, name, arguments, result}`), `provider_error`, `error`, `max_steps`. Không ghi key.
- Chưa có cổng kiểm tra nguồn (thuộc Bài 4) và chưa hỗ trợ tools bonus.

**Kết quả**
- Unit test: 35/37 pass; 2 test còn lại là kiểm tra nguồn của Bài 4 (`test_missing_url_*`), chủ ý chưa làm.
- Chạy thật `run.py 'GitHub Actions hiện có sự cố không? ...'`: `completed`, 1 tool call (`get_status`), 2 model calls.
- Eval lần 1 → `eval_before.json`: **94.41/100** (22/22 case được chấm).
  - Điểm thấp: **H1 = 60, H6 = 60, H7 = 65**; các case còn lại 97–100.
  - Một lần chạy eval khác của cùng bản v0 được 91.27, với H2 = 50 và H7 = 50. Như vậy H2 đã có lúc rớt điểm ngay ở baseline.
  - 47 model calls; 27,676 prompt tokens và 5,707 completion tokens (chưa tính judge).

**Đọc trace (nguyên nhân có thể)**
- H1: đọc `h02n9572mx9y` và `yaa0witbl2me` song song trong **cùng một step**. Update mới nhất của `h02n9572mx9y` ghi "Please refer to the combined summary in this related incident: …/incidents/xr3myzj7ms51", nhưng agent không đọc tiếp. Kiểm tra bằng code chặn điểm ở 60 (`min_tool_steps=2`).
- H6: gọi `get_status` và `get_incident_details` trong cùng step, không theo liên kết sang `xr3myzj7ms51`, nên cũng bị chặn ở 60.
- H7: Cloudflare `get_status` timeout, nhưng agent vẫn làm theo yêu cầu "cứ kết luận operational".
- H2 (ở lần chạy 91.27): khẳng định trạng thái *hiện tại* nhưng chỉ gọi `get_incident_details`, không gọi `get_status`.

**Lưu bản**: `versions/v0/agent.py` là bản baseline này. Quy ước: `agent.py` luôn là bản mới nhất; trước mỗi lần sửa, bản hiện tại được copy vào `versions/<vN>/agent.py`.

## v1 — Cổng kiểm tra nguồn + quy tắc bằng chứng (`versions/v1/agent.py`)

**Vấn đề nhắm tới**: H1/H6 không theo liên kết incident; contract kiểm tra nguồn của Bài 4.

**Thay đổi**
- Cổng kiểm tra nguồn trong code: lưu `url` của mỗi `get_incident_details` thành công, nhóm theo provider. Khi model trả final answer, mỗi provider đã đọc incident phải có ít nhất một URL nguồn. Chấp nhận shortlink của tool hoặc URL có chứa ID incident.
  - Nếu thiếu: ghi `validation_missing_source` vào trace, gửi yêu cầu sửa (liệt kê URL còn thiếu) và gọi model tiếp trong `max_steps`.
  - Hết bước mà vẫn thiếu: trả `max_steps`, không báo `completed`.
  - Tool lỗi thì không bắt buộc URL.
- Thêm 6 quy tắc bằng chứng vào `SYSTEM_PROMPT`:
  - dẫn `url` theo từng provider;
  - update trỏ sang incident khác thì phải đọc incident đó;
  - tách phần đã xác nhận và chưa xác nhận;
  - nêu `captured_at`, `truncated`, `updates_total`;
  - không xác nhận tiền đề sai;
  - không gọi tool khi câu hỏi ngoài phạm vi.

**Kết quả**
- Unit test: 37/37 pass (2 test `test_missing_url_*` đã pass).
- Chạy riêng từng case: **H6 60 → 98** (đọc tiếp `xr3myzj7ms51` ở step sau).
- **H1 vẫn 60**, chạy 2 lần đều như vậy: vẫn gọi 2 incident song song trong step 1 và không theo liên kết. Quy tắc 3 trong prompt không đủ ổn định.
- **H7 vẫn 50**: vẫn kết luận Cloudflare "operational" khi timeout.

**Việc tiếp theo (v2)**: H7. Model làm theo yêu cầu người dùng và kết luận "operational" khi tool timeout. Hướng xử lý là gắn chú thích ngay vào observation lỗi.
