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
- Eval lần 1 → `eval_before.json`: **91.27/100** (22/22 case được chấm).
  - Điểm thấp: **H1 = 60, H2 = 50, H6 = 60, H7 = 50**; các case còn lại 97–100.

**Đọc trace (nguyên nhân có thể)**
- H1/H6: không đọc incident được trỏ tới (H1 đọc `h02n9572mx9y`/`yaa0witbl2me` nhưng không đọc `xr3myzj7ms51`; H6 chưa tổng hợp đủ timeline và giới hạn dữ liệu cắt).
- H2: khẳng định trạng thái *hiện tại* nhưng chỉ gọi `get_incident_details`, không gọi `get_status`.
- H7: không báo "chưa xác định" cho Cloudflare khi `get_status` timeout, mà theo yêu cầu người dùng.

**Lưu bản**: `versions/v0/agent.py` là bản baseline này. Quy ước: `agent.py` luôn là bản mới nhất; trước mỗi lần sửa, bản hiện tại được copy vào `versions/<vN>/agent.py`.

**Việc tiếp theo (v1)**: cổng kiểm tra nguồn theo từng provider + quy tắc bằng chứng trong prompt.
