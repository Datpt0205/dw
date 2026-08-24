# Hướng dẫn tổ chức mã nguồn (tiếng Việt)

> Tài liệu onboarding. Dành cho người đến từ mô hình web app truyền thống
> (`frontend/` + `backend/`, agent nằm trong `backend/services/`) và cần hiểu vì sao
> repo này lại chia thành `apps/` + 10 package trong `packages/python/`, và vì sao mỗi
> bounded context lại chia tiếp thành `domain / application / workflows / adapters /
> presentation`.
>
> Nguồn chuẩn về kiến trúc vẫn là
> [`Digital_Worker_Source_Base_Blueprint_v2.md`](./Digital_Worker_Source_Base_Blueprint_v2.md).
> Tài liệu này chỉ giải thích **cách đọc cây thư mục**.

---

## 0. Điều cần đổi trước tiên: trục để chia thư mục

Mô hình quen thuộc chia theo **"code này thuộc loại gì"**:

```
backend/
  controllers/   ← tất cả controller
  services/      ← tất cả service (kể cả agent)
  models/        ← tất cả model
  utils/
```

Repo này chia theo **"code này phụ thuộc vào cái gì, và ai được phép phụ thuộc vào nó"**.

Hệ quả rất cụ thể. Trong cấu trúc cũ, `controllers/order.py`, `services/order.py` và
`models/order.py` là **cùng một nghiệp vụ** bị xé làm ba chỗ; trong khi
`services/order.py` và `services/agent.py` là **hai thứ chẳng liên quan gì nhau** lại
nằm chung một thư mục. Thư mục không mang thông tin gì ngoài "đây là service" — mà rồi
mọi thứ đều thành service.

Repo này chia theo ba trục lồng nhau:

| Trục | Câu hỏi | Thể hiện ra thư mục |
|---|---|---|
| 1. Triển khai | Cái này **chạy** như một tiến trình riêng? | `apps/` vs `packages/` |
| 2. Nghiệp vụ | Cái này thuộc **miền nghiệp vụ** nào? | `dw_tender` vs `dw_work_ops` |
| 3. Phụ thuộc | Cái này **phụ thuộc vào framework** hay không? | `domain / application / adapters / …` |

---

## 1. Trục 1 — `apps/` vs `packages/`

### Định nghĩa

- **`apps/*`** = thứ **chạy được**. Có entrypoint, đóng thành Docker image, có port
  lắng nghe. Ở đây: `apps/api` (FastAPI), `apps/worker` (consumer nền), `apps/web`
  (Next.js).
- **`packages/python/*`** = **thư viện**. Không tự chạy. Chỉ được import.

Quy tắc vàng: **app import package, package không bao giờ import app.**

Điều này được ép bằng máy, không phải bằng lời hứa — trong `pyproject.toml`:

```toml
[[tool.importlinter.contracts]]
name = "Contexts do not import app composition roots"
type = "forbidden"
source_modules = ["dw_tender", "dw_work_ops", "dw_platform", ...]
forbidden_modules = ["dw_api", "dw_worker"]
```

Ai viết `from dw_api...` bên trong `dw_tender` thì CI đỏ.

### Vì sao phải tách chứ không nhét hết vào `apps/api`

Vì có **nhiều hơn một** thứ chạy được. `apps/worker/src/dw_worker/consumers/ingest.py`
cần xử lý outbox và ingest tài liệu. Nếu logic tender nằm trong
`apps/api/src/dw_api/services/tender.py`, worker sẽ phải:

```python
from dw_api.services.tender import ...   # worker giờ kéo theo fastapi, uvicorn
```

Worker nền tự nhiên phải cài FastAPI và Uvicorn để chạy một vòng lặp đọc database. Và
chiều mũi tên bị sai: tiến trình này phụ thuộc vào composition root của tiến trình kia.

Với cấu trúc hiện tại, `apps/worker/pyproject.toml` khai báo đúng thứ nó cần:

```toml
dependencies = ["dw-kernel", "dw-platform", "dw-knowledge", "dw-connectors", "dw-tender", ...]
```

Không có `fastapi`. Và nó có riêng nhóm phụ thuộc nặng:

```toml
[project.optional-dependencies]
parsers = ["docling>=2.15,<3", "torch>=2.2,<3", ...]   # vài GB, chỉ cài trong worker image
```

API image không phải mang theo torch. Lợi ích rất vật lý: image nhỏ hơn, build nhanh
hơn, bề mặt CVE hẹp hơn.

### Hình dung

`apps/` là **ổ cắm điện**; `packages/` là **thiết bị**. Cùng một thiết bị cắm được vào
nhiều ổ. Trong repo này `dw_tender` đang được cắm vào ba ổ: `apps/api`, `apps/worker`,
và `dw_evals` (bộ đánh giá).

---

## 2. Trục 2 — Bounded Context

### Khái niệm

**Bounded context** (từ Domain-Driven Design) = một vùng mà **một từ có đúng một nghĩa**.

Ví dụ ngay trong dự án này. Từ **"deadline"**:

- Trong `tender` (đấu thầu): hạn nộp hồ sơ thầu do bên mời thầu công bố, có giá trị
  pháp lý, trễ một phút là loại.
- Trong `work_ops` (họp → việc): hạn hoàn thành một action item ai đó nói trong cuộc
  họp — mềm, có thể dời.

Nếu cố làm **một** class `Deadline` dùng chung cho cả hai, kết quả là một class có 12
field optional, một nửa luôn `None`, và mỗi lần sửa cho bên này thì bên kia vỡ. Đó là lý
do có hai package riêng, và có contract cấm chúng biết đến nhau:

```toml
[[tool.importlinter.contracts]]
name = "Bounded contexts are independent (tender <-/-> work_ops)"
type = "independence"
modules = ["dw_tender", "dw_work_ops"]
```

### Vậy cái gì được dùng chung?

Cái gì **thật sự** chung thì đẩy xuống tầng dưới, và tầng dưới đó không biết gì về
nghiệp vụ:

| Package | Vai trò |
|---|---|
| `dw_kernel` | Kiểu nguyên thuỷ chung: `TenantId`, `UserId`, lỗi cơ bản, cổng `Clock`/`IdGenerator`. **Chỉ stdlib** — cấm cả pydantic. |
| `dw_platform` | Năng lực nền tảng: identity, authorization, approval, audit, outbox. |
| `dw_agent_runtime` | Hạ tầng chạy agent: registry, tool executor, checkpoint, model gateway. |
| `dw_knowledge` | RAG gateway: chunking, embedding, truy vấn có filter tenant. |
| `dw_memory` | Bộ nhớ dài hạn của worker. |
| `dw_connectors` | ACL ra hệ ngoài (Slack/Teams/task tracker). |
| `dw_observability` | Trace, metric. |
| **`dw_tender`** | **Nghiệp vụ đấu thầu.** |
| **`dw_work_ops`** | **Nghiệp vụ họp → việc.** |
| `dw_evals` | Bộ dữ liệu + smoke eval. |

Mũi tên phụ thuộc luôn chảy **xuống**:
`dw_tender → dw_agent_runtime → dw_platform → dw_kernel`. Không bao giờ ngược.

Kiểm chứng bằng cách mở `dependencies` trong `pyproject.toml` của từng package —
`dw_memory` chỉ khai báo `kernel, knowledge, platform`, nên nó **không thể** import
`dw_tender` dù có gõ nhầm: package đó không tồn tại trong môi trường resolve của nó.

---

## 3. Trục 3 — Năm tầng bên trong một context

Đây là phần mới nhất so với mô hình quen thuộc. Mở
`packages/python/dw_work_ops/src/dw_work_ops/`:

```
domain/          ← luật nghiệp vụ thuần
application/     ← use case + PORTS (interface)
adapters/        ← ADAPTERS (implementation) — SQL, HTTP, Slack…
presentation/    ← router HTTP
workflows/       ← đồ thị agent, có version
```

### 3.1 `domain/` — luật nghiệp vụ, không biết gì về máy móc

`domain/entities.py`:

```python
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_work_ops.domain.value_objects.confidence import Confidence, RiskLevel

@dataclass(slots=True)
class MeetingSession:
    id: MeetingId
    tenant_id: TenantId
    title: str
    status: MeetingStatus = MeetingStatus.CREATED
```

Chú ý: **không có** `from sqlalchemy`, **không có** `from fastapi`, **không có**
`from openai`. Có contract ép điều đó:

```toml
name = "Domain layers never import frameworks or providers"
source_modules = ["dw_tender.domain", "dw_work_ops.domain", "dw_platform.domain"]
forbidden_modules = ["fastapi", "sqlalchemy", "langgraph", "qdrant_client", "openai", ...]
```

**Vì sao khắt khe vậy?** Ba lý do thực dụng:

1. **Test chạy trong mili-giây.** Muốn kiểm tra "action item có risk cao thì bắt buộc
   phải approve" — import dataclass, gọi hàm, `assert`. Không cần Postgres, không cần
   API key.
2. **Luật nghiệp vụ sống lâu hơn framework.** SQLAlchemy 1 → 2 đã là một cuộc di cư đau
   đớn. Nếu `MeetingSession` kế thừa từ SQLAlchemy, luật nghiệp vụ bị trói vào lịch phát
   hành của một thư viện ORM.
3. **Đọc được.** Người nghiệp vụ mở `domain/policies.py` vẫn hiểu, vì trong đó không có
   `session.execute(select(...))`.

Trong mô hình cũ, `models/` thường là ORM model — tức đã trộn luật nghiệp vụ với schema
database. `domain/` khác `models/` chính ở chỗ đó.

### 3.2 `application/ports.py` — khái niệm quan trọng nhất

**Port** = một `Protocol` (interface) mô tả **cái mà nghiệp vụ cần**, viết bằng ngôn ngữ
nghiệp vụ, không nhắc đến công nghệ.

`application/ports.py`:

```python
class MeetingRepositoryPort(Protocol):
    async def add(self, meeting: MeetingSession) -> None: ...
    async def get(self, meeting_id: MeetingId) -> MeetingSession | None: ...
    async def save(self, meeting: MeetingSession) -> None: ...
```

Đọc kỹ: nó nói *"tôi cần lưu và lấy được MeetingSession"*. Nó **không** nói Postgres,
không nói bảng, không nói SQL. Nó cũng không phải abstract class chờ ai kế thừa —
`Protocol` của Python là structural typing: bất cứ class nào có đủ các method đó đều hợp
lệ, không cần khai báo kế thừa.

**Adapter** = phần cài đặt thật, ở `adapters/persistence/repositories.py`:

```python
import sqlalchemy as sa
from dw_work_ops.application.ports import MeetingRepositoryPort   # ← adapter import port
from dw_work_ops.domain.entities import MeetingSession
```

### 3.3 Dependency Inversion — chỗ mũi tên bị đảo

Đây là điểm mấu chốt. Kiến trúc quen thuộc:

```
controller  →  service  →  repository  →  database
                            (service phụ thuộc vào repository cụ thể)
```

Kiến trúc ở đây:

```
                    ┌─────────────────┐
   presentation ──► │  application    │ ◄── adapters
                    │  (ports + use   │
                    │   cases)        │
                    └────────┬────────┘
                             ▼
                          domain
```

Mũi tên từ `adapters` **chỉ vào** `application`, không phải ngược lại. Nghĩa là **tầng
hạ tầng phụ thuộc vào tầng nghiệp vụ**, chứ không phải nghiệp vụ phụ thuộc hạ tầng. Tên
gọi "Dependency Inversion" là vì thế — mũi tên lộn ngược so với trực giác.

Cách nhớ: **nghiệp vụ ra đề, hạ tầng đi thi.** `application/ports.py` là đề bài.
`adapters/persistence/repositories.py` là bài làm bằng SQLAlchemy. Nếu mai đổi sang
MongoDB, viết bài làm khác; đề bài không đổi, và `handlers.py` không sửa một dòng.

"Hexagonal" (kiến trúc lục giác) chỉ là cách vẽ khác của cùng ý tưởng: nghiệp vụ ở giữa
như một hình lục giác, mỗi cạnh là một port, cắm được nhiều loại adapter khác nhau vào
cùng một cạnh — SQL thật khi chạy production, fake in-memory khi chạy test.

### 3.4 `application/handlers.py` — use case

`handlers.py` là nơi một thao tác nghiệp vụ diễn ra trọn vẹn:

```python
@dataclass
class CreateMeetingHandler:
    uow_factory: WorkOpsUnitOfWorkFactory   # ← toàn PORT, không phải class cụ thể
    storage: TranscriptStoragePort
    authorization: ScopeAuthorizationService
    entitlement: PlanEntitlementService
    clock: UtcClock
    id_generator: IdGenerator

    async def handle(self, cmd: CreateMeetingCommand, context: AccessContext) -> uuid.UUID:
        await self.authorization.require(context=context, action="work_ops.write", ...)
        await self.entitlement.require_feature(context, WORK_OPS_FEATURE)
        ...
```

Ba điều đáng chú ý:

- **Constructor injection**: mọi phụ thuộc đi vào qua field của dataclass. Không có
  `db = get_db()` toàn cục, không có singleton. Test truyền fake vào là xong.
- Kể cả `clock: UtcClock` và `id_generator: IdGenerator` cũng là port. Nghe hơi quá,
  nhưng nó làm test **tất định**: bơm clock giả trả về mốc thời gian cố định, kết quả
  lặp lại được 100%.
- **`authorization` và `entitlement` tách riêng.** Hai câu hỏi khác nhau: *"người này có
  quyền không?"* (authorization) vs *"gói cước của tenant này có bật tính năng đó
  không?"* (entitlement). Gộp lại là một lỗi kinh điển.

### 3.5 `presentation/` — router mỏng

`presentation/api.py`:

```python
def build_work_ops_router(
    *,
    create_meeting: CreateMeetingHandler,
    get_meeting: GetMeetingHandler,
    ...
) -> APIRouter:
```

Nó là một **factory nhận handler đã dựng sẵn từ bên ngoài**, chứ không tự đi tạo
repository. Router chỉ làm ba việc: parse request (Pydantic), gọi handler, trả response.

Chính vì thế, đưa nghiệp vụ này lên một kênh khác — Slack, cron, CLI — chỉ cần viết một
`presentation` khác gọi cùng handler. Xem `apps/api/src/dw_api/channels/slack.py`.

### 3.6 `workflows/` — agent nằm ở đây

```
workflows/
  registry.py
  v1/
    state.py     ← state của đồ thị, có kiểu, có version
    nodes.py     ← từng bước
    graph.py     ← nối các bước
```

Docstring của `workflows/v1/nodes.py` nói thẳng nguyên tắc:

> *Nodes are small, deterministic where possible, and speak only to ports. LLM steps
> validate output into Pydantic schemas; assignees resolve against the organization
> directory, never from model-invented identifiers.*

Node **không** gọi `openai.chat.completions.create()` — nó gọi qua `ModelRequest` từ
`dw_agent_runtime.ports`. Node **không** viết SQL — nó gọi handler/port. Node chỉ lo
**trình tự**: bước nào trước, bước nào sau, khi nào rẽ nhánh, khi nào dừng chờ người
duyệt.

`v1/` trong đường dẫn là có chủ ý: khi sửa đồ thị, các run đang dở dang trong database
vẫn tham chiếu tới `v1`. Thêm `v2/` bên cạnh chứ không sửa đè, nếu không những run cũ sẽ
resume vào một đồ thị đã đổi hình dạng.

---

## 4. Vì sao agent không nằm gọn trong `services/`?

Vì cái thường được gọi là "agent" thật ra là **bốn thứ khác nhau bị dính vào nhau**. Một
file `services/agent.py` điển hình chứa:

| Đoạn code trong `services/agent.py` | Bản chất | Ở repo này nó nằm đâu |
|---|---|---|
| `openai.ChatCompletion.create(...)`, quản lý API key, retry | Hạ tầng nhà cung cấp | `dw_agent_runtime/model/gateway.py` + `adapters/openai_compatible.py` |
| Chuỗi bước: tóm tắt → trích action → gán người → chờ duyệt | Điều phối | `dw_work_ops/workflows/v1/` |
| "Risk cao thì bắt buộc duyệt", "assignee phải có thật trong tổ chức" | Luật nghiệp vụ | `dw_work_ops/domain/policies.py`, `domain/entities.py` |
| Gọi Slack/task tracker để tạo task thật | Tác dụng phụ ra ngoài | `dw_connectors/` + `adapters/dispatch/tool.py` |

Khi cả bốn nằm chung một file, ta mất bốn thứ cùng lúc:

1. **Không test được luật nghiệp vụ nếu không có LLM.** Muốn kiểm tra "risk cao phải
   duyệt" mà phải gọi OpenAI thật: tốn tiền, chậm, kết quả không tất định.
2. **Không tái dùng được từ worker.** Worker cần dispatch task đã duyệt, nhưng logic đó
   bị chôn trong file cùng chỗ với code gọi FastAPI.
3. **Không version được.** Sửa prompt hôm nay thì các run đang chờ duyệt từ hôm qua
   resume vào prompt mới, và không giải thích được vì sao kết quả lệch.
4. **Không chặn được tác dụng phụ.** Khi lời gọi Slack nằm lẫn trong hàm agent, không có
   một chỗ duy nhất để hỏi *"thao tác này có cần duyệt không? đã có idempotency key
   chưa? đã ghi audit chưa?"*. Ở đây, chỗ duy nhất đó là `dw_agent_runtime/executor.py`.

Điểm 4 chính là ranh giới giữa "chatbot demo" và "digital worker chạy thật trong doanh
nghiệp". Một agent tự tạo 200 task lúc 2 giờ sáng vì hiểu nhầm một transcript là chuyện
hoàn toàn có thật.

Nguyên tắc này được ép ở mức file. `dw_agent_runtime/adapters/langgraph_runner.py` là
chỗ **duy nhất** được `import langgraph`:

```toml
name = "LangGraph only inside runtime adapters and demo-graph testing module"
source_modules = ["dw_agent_runtime.contracts", ".ports", ".registry", ".tools", ".executor", ...]
forbidden_modules = ["langgraph", "langchain_core", "langchain"]
```

Docstring của chính file đó viết: *"LangGraph never leaks outside this adapter
(import-linter enforced)."* Nghĩa là nếu sau này LangGraph không còn phù hợp, vùng phải
viết lại là **một file ~230 dòng**, không phải toàn bộ codebase.

---

## 5. Composition Root — chỗ mọi thứ được nối lại

Nếu mọi tầng đều chỉ nhận interface, thì ai tạo ra object thật? **Đúng một chỗ**:
`apps/api/src/dw_api/bootstrap.py`, mở đầu bằng:

> *Composition root: the only place concrete adapters are wired together. Tests build
> their own container with fake ports; production wiring lives here.*

Đây là file duy nhất trong hệ thống được phép biết rằng "repository là SQLAlchemy" và
"model provider là OpenAI-compatible". Nó dựng container; `apps/api/src/dw_api/main.py`
gắn router:

```python
from dw_work_ops.presentation.api import build_work_ops_router
app.include_router(build_work_ops_router(create_meeting=..., ...), prefix="/api/v1")
```

Test thì dựng container riêng với `MockModelAdapter`, `MockTaskConnectorAdapter` — cùng
những port đó, adapter khác. Không cần monkeypatch, không cần mocking framework.

### Đường đi một request, xuyên hết mọi tầng

```
POST /api/v1/work-ops/meetings
  │
  ├─ apps/api/src/dw_api/main.py            ← app thật, mount router
  ├─ apps/api/src/dw_api/middleware/        ← request id, rate limit
  ├─ dw_work_ops/presentation/api.py        ← validate Pydantic, gọi handler
  ├─ dw_work_ops/application/handlers.py    ← authz → entitlement → tạo entity → lưu
  │     ├─ dw_work_ops/domain/entities.py         ← MeetingSession, luật thuần
  │     ├─ (port) TranscriptStoragePort           ← "tôi cần lưu file"
  │     │     └─ adapter MinIO, do bootstrap.py nối vào
  │     └─ (port) WorkOpsUnitOfWorkFactory        ← "tôi cần một transaction"
  │           └─ dw_work_ops/adapters/persistence/repositories.py  ← SQL thật + SET LOCAL tenant
  └─ response
```

Bốn tầng đầu đọc như tiếng Việt nghiệp vụ. Chỉ tầng cuối mới có SQL.

---

## 6. Quy tắc thực hành: "file này để đâu?"

Hỏi lần lượt, dừng ở câu đầu tiên trả lời "có":

1. **Nó `import` một SDK bên ngoài (sqlalchemy, qdrant, slack_sdk, openai, boto3)?**
   → `adapters/`. Không có ngoại lệ.
2. **Nó định nghĩa route HTTP / handler webhook / lệnh CLI?**
   → `presentation/` (nếu thuộc nghiệp vụ) hoặc `apps/*` (nếu thuộc riêng tiến trình đó).
3. **Nó quyết định thứ tự các bước, có LLM, có điểm dừng chờ người duyệt?**
   → `workflows/vN/`.
4. **Nó điều phối một use case: kiểm quyền → mở transaction → gọi domain → lưu?**
   → `application/handlers.py`.
5. **Nó là một quy tắc đúng/sai độc lập với mọi công nghệ?**
   → `domain/`.
6. **Nó dùng chung cho cả tender lẫn work_ops?**
   → tụt xuống `dw_platform` (nghiệp vụ nền tảng) hoặc `dw_kernel` (nguyên thuỷ thuần).

> ⚠️ Bẫy ở bước 6: **hai chỗ dùng chung một cái tên không có nghĩa là chung một khái
> niệm.** Nếu `tender.Deadline` và `work_ops.Deadline` chỉ giống nhau về chữ, giữ nguyên
> hai bản. Trùng lặp có chủ đích rẻ hơn một abstraction sai rất nhiều.

Một quy tắc chéo, ép bởi CI: **`domain/` chỉ được import stdlib + `dw_kernel`.** Đó là
bài kiểm tra nhanh nhất khi phân vân.

---

## 7. Cái giá phải trả — và khi nào đừng làm thế này

**Chi phí:**

- Thêm một tính năng đơn giản có thể phải chạm 4 file (port, handler, adapter, route)
  thay vì 1.
- 10 file `pyproject.toml` phải bảo trì.
- Đổi signature trong `dw_kernel` gây sửa lan ra nhiều package.
- Người mới mất khoảng một tuần mới thấy thoải mái.

**Đừng dùng cấu trúc này khi:** chỉ có một tiến trình, một miền nghiệp vụ, dưới ~5k
dòng, đội 1–2 người, không có kế hoạch tách service. Lúc đó `backend/services/` là lựa
chọn đúng, và mọi tầng ở trên chỉ là nghi thức.

**Nó bắt đầu có lãi khi:** ≥2 tiến trình dùng chung logic (ở đây: 3), ≥2 miền nghiệp vụ
có từ vựng xung đột (ở đây: 2), yêu cầu multi-tenant có RLS, và có tác dụng phụ ra hệ
thống thật cần duyệt + audit. Repo này thoả cả bốn.

Một điểm nên tự canh: `dw_memory` và `dw_observability` hiện khá mỏng. Nếu vài tháng nữa
chúng vẫn không có biến thể thật hay test seam thật thì đáng cân nhắc gộp lại — package
tồn tại để **giữ một ranh giới có thật**, không phải để trông cho có tổ chức. Riêng
`dw_kernel` phải giữ riêng, vì contract "pure stdlib" chỉ chạy được khi nó là một root
package độc lập.

---

## 8. Đường học ngắn nhất

Mở `dw_work_ops` (nhỏ vừa đủ) và đọc theo đúng thứ tự:

1. `domain/entities.py`
2. `application/ports.py`
3. `application/handlers.py`
4. `adapters/persistence/repositories.py`
5. `presentation/api.py`

Đọc xong năm file đó là nắm được toàn bộ mô hình. `dw_tender` chỉ là cùng khuôn ở quy mô
lớn hơn nhiều lần.
