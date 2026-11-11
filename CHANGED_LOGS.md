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

## v2 — `agent_note` cho observation lỗi (`versions/v2/agent.py`)

**Vấn đề nhắm tới**: H7. Khi tool timeout, model làm theo yêu cầu người dùng và kết luận Cloudflare "operational".

**Thay đổi**
- `_annotate_error` thêm `agent_note` vào bản sao của observation có `ok: false`, ngay chỗ model đọc kết quả tool. Dict gốc của tool không bị sửa. Nội dung note theo loại lỗi:
  - timeout, lỗi mạng hoặc provider không hỗ trợ → "Trạng thái của `{provider}`: **CHƯA XÁC ĐỊNH**. Lỗi tool không phải trạng thái dịch vụ; không kết luận operational/outage, kể cả khi người dùng yêu cầu";
  - `INCIDENT_NOT_FOUND` → không xác nhận cũng không bác bỏ, không bịa link;
  - `INVALID_ARGUMENTS` → sửa tham số theo schema;
  - `UNKNOWN_TOOL` → chỉ dùng tools được cung cấp.
- Thêm `tests/test_improvements.py` (7 test): nguồn theo từng provider, chấp nhận URL dạng `/incidents/<id>`, `get_status` không bắt buộc URL incident, note cho timeout và not-found, kết quả thành công không có note, không sửa dict của tool.

**Kết quả**
- Unit test: 44/44 pass.
- Chạy riêng từng case: **H7 50 → 100**. A3 và E6 (cũng là case timeout) giữ 100.

## Eval lần 2 (bản v2, cả bộ 22 case): **95.14/100**

Ở lần chạy đầu, E2 không được chấm vì judge trả về JSON hỏng. Theo GUIDE, tôi chạy lại riêng E2 (được 100) rồi ghép vào kết quả.

| Case | v0 (`eval_before.json`) | v2 | Ghi chú từ trace |
|---|---|---|---|
| H7 | 65 | **100** | Báo Cloudflare chưa xác định khi timeout |
| H6 | 60 | **97** | ⚠️ Điểm cao nhưng sai, xem bên dưới |
| H1 | 60 | **60** | Vẫn gọi `h02n9572mx9y` và `yaa0witbl2me` song song trong step 1, không đọc `xr3myzj7ms51` |
| H2 | 100 | **50** | Chỉ gọi `get_incident_details`, không gọi `get_status`, nên bị chặn ở 50 |
| Các case khác | 97–100 | 94–100 | Dao động ±1–6 điểm (E1 100 → 94, E5 99 → 96) |

- Model calls: 47 → 52. Prompt tokens: 27,676 → 47,341 (+71%, do system prompt dài hơn và có thêm bước). Completion tokens: 5,707 → 7,725.
- Cổng nguồn được kích hoạt **1 lần**, ở H6: model trả lời mà không có URL của `h02n9572mx9y`, nhận lời nhắc và sửa ở step 4.

**Phát hiện**
- **H6 là judge chấm sai**:
  - Ở step 2, agent gọi `get_incident_details` với ID **`xr3myzjms51`** (gõ thiếu số 7) và nhận `INCIDENT_NOT_FOUND`.
  - Câu trả lời ghi link sai `…/incidents/xr3myzms51` và nói "không đủ dữ liệu về tóm tắt gộp".
  - Judge vẫn viết rằng agent "liên kết đến incident gộp xr3myzj7ms51" và cho 97.
  - Như vậy quy tắc trong prompt khiến model *cố* đi theo liên kết, nhưng tự chép lại ID thì có thể sai.
- **H1 và H2**: quy tắc trong prompt không đủ ổn định cho hành vi nhiều bước. H2 cũng từng bị 50 ở một lần chạy v0, nên đây là hành vi không ổn định, không phải do thay đổi của v2.

**Việc tiếp theo (v3)**: đưa hai hành vi này từ prompt vào code.
- (1) Code đọc ID incident được trỏ tới từ nội dung update và nhắc model đọc đúng ID đó. ID được lấy nguyên văn từ tool result, nên tránh được lỗi gõ sai ID như H6.
- (2) Câu hỏi về trạng thái hiện tại thì phải có `get_status`.

## v3 — Chuyển H1/H2 từ prompt sang code (`versions/v3/agent.py`)

**Vấn đề nhắm tới**
- H1/H6: không đọc, hoặc đọc sai ID, incident được update trỏ tới.
- H2: khẳng định trạng thái hiện tại mà không gọi `get_status`.

**Thay đổi**
1. **Nhắc đọc incident được trỏ tới (`_flag_references`)**:
   - Khi `get_incident_details` thành công, code quét nội dung update tìm link `/incidents/<id>` và suy provider từ host.
   - Nếu incident đó chưa được gọi, code gắn `agent_note` vào observation, kèm lời gọi mẫu với **ID nguyên văn**, ví dụ `get_incident_details(provider='github', incident_id='xr3myzj7ms51')`.
   - Chốt chặn cuối: nếu model trả lời mà vẫn chưa gọi incident đó, agent ghi `validation_unread_reference`, nhắc **một lần** rồi gọi model tiếp.
   - Không nhắc ở step cuối: khi đó không còn bước để gọi tool, nhắc chỉ làm `completed` thành `max_steps`.
   - Một ID gõ sai không được tính là đã đọc.
   - Trong snapshot chỉ có 2 liên kết loại này (`h02n9572mx9y` → `xr3myzj7ms51`, `qpfv5p86dmrl` → `djlmxz2zd0j7`), nên cổng không kích hoạt bừa.
2. **Quy tắc `get_status` cho trạng thái hiện tại**:
   - Thêm quy tắc 7 vào prompt. Chạy H2 hai lần, cả hai vẫn 50, nên thêm chốt chặn bằng code.
   - Câu hỏi có từ chỉ thời điểm hiện tại (`đang`, `hiện tại`, `hiện có`, `hiện nay`, `bây giờ`), có nhắc provider, agent đã dùng tool nhưng chưa gọi `get_status` cho provider đó → ghi `validation_missing_status` và nhắc một lần.
   - Bản đầu của điều kiện còn bắt cả "outage", "operational", "sập" và kích hoạt ở H3 ("vừa làm Cloudflare sập"). Agent khi đó dẫn trạng thái "Partial System Outage" không liên quan tới ID giả, và H3 giảm **100 → 89**. Tôi thu hẹp điều kiện về từ chỉ thời điểm; chạy lại H3 được 100. Lúc này chỉ 5 câu hỏi đủ điều kiện (E1, E6, H2, H5, H7), và chỉ H2 thiếu `get_status`.
3. Thêm 8 test vào `tests/test_improvements.py`:
   - 5 test `ReferenceGateTests`: observation chứa đúng ID, nhắc một lần rồi đọc, chỉ nhắc một lần, không nhắc ở step cuối, gõ sai ID vẫn bị nhắc;
   - 3 test `StatusGateTests`: câu hỏi trạng thái hiện tại phải có `get_status`, đã gọi thì không nhắc, câu ngoài phạm vi hoặc hỏi lịch sử thì không nhắc.

**Kết quả chạy riêng (2 lần mỗi case)**
- H1: **99, 98**. Model đọc `xr3myzj7ms51` ngay ở step 2 nhờ `agent_note`, không cần đến chốt chặn cuối.
- H2: lúc chỉ có quy tắc prompt được 50, 50; có cổng code được **100, 100**.
- H6: 97, lần này đọc đúng `xr3myzj7ms51` (`ok: true`).
- H3: 89 với điều kiện rộng, **100** sau khi thu hẹp. H4: 100, không gọi tool.
- Unit test: 52/52 pass.

## Eval lần 3 (bản v3, cả bộ) → `eval_after.json`: **99.59/100**

| Chỉ số | v0 `eval_before.json` | v2 (eval lần 2) | v3 `eval_after.json` |
|---|---|---|---|
| Điểm tổng | 94.41 | 95.14 | **99.59** |
| H1 | 60 | 60 | **99** |
| H2 | 100 | 50 | **100** |
| H6 | 60 | 97 (judge chấm sai) | **100** |
| H7 | 65 | 100 | **100** |
| Case thấp nhất | 60 | 50 | 97 (A6) |
| Model calls | 47 | 52 | 53 |
| Prompt tokens | 27,676 | 47,341 | 50,859 |
| Completion tokens | 5,707 | 7,725 | 6,815 |

- Đã đối chiếu trace của H1, H6, A6: cả ba đọc `xr3myzj7ms51` thành công và dẫn URL của nó. H2 gọi `get_status` sau lời nhắc. Không còn trường hợp điểm cao mà hành vi sai.
- Trong lần chạy này, chỉ có 1 lần nhắc bằng cổng (`validation_missing_status` ở H2). H1 và H6 làm đúng ngay nhờ `agent_note`.
- Các case khác dao động 97–100 (E1 98, E3 98, A6 97, A7 99), không có lỗi hành vi trong trace.
- Chi phí: prompt tokens tăng ~84% so với v0 (system prompt dài hơn, `agent_note` và các bước nhắc), đổi lại agent không còn đi sai ở các case nhiều bước.

**Giới hạn**
- Mỗi phiên bản chỉ chạy cả bộ một lần. Riêng H1, H2 chạy 2 lần.
- Judge (gpt-4.1) có thể chấm sai: ví dụ H6 ở eval lần 2.
- Các cổng dựa trên quy tắc chuỗi (regex link `/incidents/<id>`, từ chỉ thời điểm hiện tại). Chúng không hiểu ngữ nghĩa và có thể bỏ sót cách diễn đạt khác.
- Điều kiện của cổng `get_status` đã được chỉnh sau khi thấy H3, nên có nguy cơ khớp quá sát bộ eval.

## v4 — Bonus: kết nối 5 provider, giới hạn retry 429, Retry-After (`versions/v4/agent.py`)

**Thay đổi**
1. **Kết nối tools**:
   - Agent dùng `getattr(tools, 'schemas', SCHEMAS)`.
   - Khi tools có `system_prompt` (bộ bonus), system prompt = `tools.system_prompt` + `BONUS_RULES`. `BONUS_RULES` có 7 quy tắc:
     - nguồn và `captured_at` theo từng provider;
     - 429 không phải outage, tối đa 3 lần thử;
     - sửa `offset`/`limit` khi tham số sai;
     - đọc tiếp bằng `next_offset`;
     - bỏ qua dữ liệu nhiễu;
     - không bịa thông tin cho provider không có tool;
     - không suy nhân quả giữa các provider.
   - Tools bài chính chạy như cũ.
2. **Retry 429 bằng code (`_run_tool`)**:
   - Đếm theo cặp (tool, provider). Sau 3 lần `RATE_LIMITED`, agent **không gọi API nữa**: trả `RETRY_LIMIT_REACHED` cho model và ghi event `tool_blocked`. Gọi thành công thì bộ đếm reset.
   - Đọc `retry_after_seconds` hoặc header `Retry-After` (số giây hoặc HTTP-date). Thời gian chờ ≤ 5 giây thì `sleep` và ghi `retry_wait`; lâu hơn, hoặc `retriable: false`, thì dừng thử ngay.
   - `agent_note` cho 429 nói rõ "KHÔNG phải outage" và số lượt còn lại.
3. **Tổng quát hoá các cổng của v3 cho 5 provider**:
   - Danh sách provider được hỗ trợ suy từ schema (enum `provider` và tên `get_<provider>_status`).
   - Cổng `get_status` nhận cả `get_<provider>_status` và nhắc đúng tên tool, ví dụ `get_npm_status()`.
4. **Sửa lỗi tiềm ẩn ở `_flag_references`**:
   - Bản v3 gặp host lạ thì gán cho provider đang đọc.
   - Incident DigitalOcean `lrrw084g3whn` có link `status.claude.com/incidents/8z7l5zcy0v3b`, nên agent sẽ bị nhắc gọi `get_incident_details('digitalocean', '8z7l5zcy0v3b')` và chắc chắn nhận `NOT_FOUND`.
   - Giờ host không thuộc provider được hỗ trợ thì bỏ qua.
   - Link chéo hợp lệ vẫn được nhận: Vercel `sps6n39gm4sg` → GitHub `93njd414rpbx`.
5. **Thêm 8 test**:
   - 5 test `RateLimitTests`: 429 kéo dài chỉ gọi 3 lần, 429 một lần rồi thành công, Retry-After ngắn thì chờ, Retry-After dài thì dừng, prompt bonus;
   - 3 test `BonusGateTests`: bỏ qua host lạ, nhận link chéo provider, cổng `get_status` nhắc đúng tool bonus.

**Kết quả**
- Unit test: 60/60 pass trong `tests/`; 3/3 pass trong `bonus/`.
- Eval bonus cả bộ (`logs/eval_bonus_v4.json`): **89.2/100 → 13.38/15**.
  - Trung bình 2.8 model calls mỗi case. Prompt tokens 45,811, completion tokens 4,453.
  - B3, B4, B7, B8, B9: 100. B1, B5: 98. B2: 96.
  - Trace cho thấy cơ chế mới chạy đúng:
    - B3 gặp 429 rồi thử lại thành công;
    - B4 thử đúng 3 lần rồi dừng, báo Vercel chưa xác định;
    - B5 sửa tham số rồi gọi lại;
    - B2 đọc trang `offset=3` rồi đọc incident GitHub `93njd414rpbx` nhờ `agent_note`.
  - **B10 = 50**:
    - Vercel trả 429 ở lần gọi đầu.
    - `agent_note` báo còn 2 lượt thử, nhưng model trả lời luôn rằng Vercel chưa xác định, không thử lại.
    - Kiểm tra bằng code yêu cầu gọi `get_vercel_status` ít nhất 2 lần.
  - **B6 = 50**: chỉ gọi `get_vercel_status` và `get_npm_status` rồi so sánh dựa trên danh sách tiêu đề, **không đọc chi tiết incident nào**. Case bắt buộc có `get_incident_details`.

**Việc tiếp theo (v5)**
- (1) Khi model sắp trả lời mà vẫn còn một 429 có thể thử lại và chưa có lần gọi thành công, nhắc model thử lại.
- (2) Câu hỏi đối chiếu incident cụ thể (phạm vi, ảnh hưởng) thì phải đọc chi tiết incident, không chỉ dựa vào danh sách tiêu đề.
