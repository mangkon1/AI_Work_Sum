# AI Agent Router

ตัวกลาง (router / orchestrator) แบบ local ให้ AI agent หลายตัว **ส่งงานหากันโดยระบุชื่อปลายทางชัดเจน**
เช่น OpenCode (agent หลัก) สั่งงานให้ Grok รีวิวโค้ด แล้วรับคำตอบกลับมา

- **OpenCode คือ agent หลัก** — agent อื่นจะทำงานก็ต่อเมื่อถูกระบุเป็น `target` เท่านั้น
- **ไม่มี broadcast** — หนึ่งคำขอ = หนึ่ง agent ปลายทาง
- ใช้ได้ 2 ทาง: **REST API** (`POST /invoke`) และ **MCP server ในตัว** (`/mcp`, `/sse`, หรือ `--mcp-stdio`)
- เพิ่ม agent ใหม่ได้ด้วยการแก้ `config.yaml` อย่างเดียว (agent ชนิด `http` ทั่วไป)
- build เป็นไฟล์เดียว `AI-Agent-Router.exe` ด้วย `build.bat`

```
 ┌──────────┐  MCP (invoke_agent)   ┌──────────────────────────┐   xAI API    ┌──────┐
 │ OpenCode │ ────────────────────► │     AI Agent Router      │ ───────────► │ Grok │
 └──────────┘  หรือ POST /invoke     │  127.0.0.1:8080          │              └──────┘
 ┌──────────┐                       │  - auth X-API-Key        │  HTTP/webhook ┌────────────┐
 │  Cursor  │ ────────────────────► │  - route ตาม target      │ ────────────► │ agent อื่นๆ │
 └──────────┘                       │  - log + request_id      │              └────────────┘
                                    └──────────────────────────┘
```

---

## เปิดโปรแกรม (GUI) — สำหรับมือใหม่ ไม่ต้องใช้ command line

**แค่ดับเบิลคลิก `AI-Agent-Router.exe` ก็ใช้งานได้เลย** ไม่ต้องแก้ไฟล์ `.env` เอง ไม่ต้องพิมพ์คำสั่ง

1. **ดับเบิลคลิก `AI-Agent-Router.exe`** → หน้าต่างโปรแกรมเปิดขึ้น (ไม่มีหน้าจอดำ console)
2. ครั้งแรกโปรแกรมจะ **สร้างกุญแจ (Router Key) แบบสุ่มให้อัตโนมัติ** และบันทึกลงไฟล์ `.env` ข้าง EXE
3. เซิร์ฟเวอร์ **เริ่มทำงานเอง** — ไฟเขียว "กำลังทำงาน" ที่ `http://127.0.0.1:8080`
4. (ถ้าจะใช้ Grok) วางกุญแจ xAI ในช่อง **"กุญแจ xAI สำหรับ Grok"** แล้วกด **บันทึก** — ไฟของ grok จะเป็นสีเขียว
5. ไปที่แท็บ **"คู่มือ / วิธีเชื่อมต่อ"** → กด **คัดลอก** config ของ OpenCode หรือ Cursor (กุญแจถูกใส่ไว้ให้แล้ว) ไปวางในไฟล์ตั้งค่าของโปรแกรมนั้น แล้วเปิด OpenCode/Cursor ใหม่
6. เปิดหน้าต่างนี้ค้างไว้ระหว่างใช้งาน — ช่อง **"บันทึกการทำงาน"** จะแสดงว่าใครส่งงานให้ใคร สำเร็จหรือไม่ • ปิดหน้าต่าง = หยุดเซิร์ฟเวอร์และออกจากโปรแกรม

![หน้าหลัก](docs/gui-main.png)
![คู่มือ / วิธีเชื่อมต่อ](docs/gui-guide.png)
<sub>ภาพตัวอย่างถ่ายบน Linux — บน Windows หน้าตาจะเป็นปุ่มสไตล์ Windows และฟอนต์ Leelawadee UI</sub>

ส่วนต่าง ๆ ในหน้าต่าง:
| ส่วน | ทำอะไร |
|---|---|
| 1) เซิร์ฟเวอร์ | ไฟสถานะ (เขียว = ทำงาน, เทา = หยุด, ส้ม = กำลังเริ่ม/หยุด, แดง = ผิดพลาด เช่นพอร์ตถูกใช้), ปุ่ม เริ่ม/หยุด, URL (คลิกเพื่อเปิด / ปุ่มคัดลอก), เปลี่ยนพอร์ต, ติ๊ก "เริ่มทำงานอัตโนมัติ" |
| 2) กุญแจ | Router Key (คัดลอก / แก้ไข / สุ่มใหม่) และกุญแจ xAI (ซ่อนได้, บันทึก) — บันทึกแล้วเซิร์ฟเวอร์รีสตาร์ทให้เอง |
| 3) AI ปลายทาง | ไฟของแต่ละ agent: **เขียว = พร้อมใช้**, **เทา = ยังไม่ตั้งค่า**, **แดง = ปิด** พร้อมคำอธิบายสั้น ๆ ว่าต้องตั้งอะไร |
| 4) บันทึกการทำงาน | log แบบอ่านง่าย เช่น `➜ opencode ส่งงานให้ grok`, `✔ grok ตอบกลับ opencode สำเร็จ (1.2 วินาที)`, `✖ ... ไม่สำเร็จ [503]` (ติ๊ก "แสดงรายละเอียดทางเทคนิค" เพื่อดู log เต็ม) |
| แท็บคู่มือ | MCP URL, X-API-Key, config ของ OpenCode/Cursor (แบบ URL และแบบ stdio) พร้อมปุ่มคัดลอก, ตัวอย่าง PowerShell, ปัญหาที่พบบ่อย |

### โหมดการเปิดโปรแกรม
| วิธีเปิด | ผลลัพธ์ |
|---|---|
| ดับเบิลคลิก / `AI-Agent-Router.exe` (ไม่มี argument) / `python main.py` | **GUI** (เริ่มเซิร์ฟเวอร์อัตโนมัติ) |
| `--gui` (ใช้ร่วมกับ `--port`, `--host`, `--config` ได้) | GUI |
| `--no-gui` หรือ `--headless` | เซิร์ฟเวอร์อย่างเดียว ไม่มีหน้าต่าง (แบบเดิม) |
| `--mcp-stdio` | MCP server ผ่าน stdio (สำหรับ OpenCode/Cursor แบบ local) |
| มี argument อื่น เช่น `--port 9000` โดยไม่มี `--gui` | เซิร์ฟเวอร์อย่างเดียว (เหมือนเวอร์ชันก่อน) |
| ตั้ง env `ROUTER_NO_GUI=1` | บังคับไม่เปิด GUI |
| เปิด GUI ไม่ได้ (ไม่มี tkinter / ไม่มีจอ เช่นบน server Linux) | เปลี่ยนเป็นเซิร์ฟเวอร์อย่างเดียวอัตโนมัติ |

> การตั้งค่าที่ GUI เขียนลง `.env`: `ROUTER_API_KEYS`, `XAI_API_KEY`, `ROUTER_PORT`, `ROUTER_GUI_AUTOSTART` (แก้ด้วยมือก็ได้)
> ต้องวาง EXE ในโฟลเดอร์ที่เขียนไฟล์ได้ (เช่น Desktop, Documents, `C:\Tools\AI-Agent-Router`) — ไม่แนะนำ `C:\Program Files`

---

## สารบัญ
0. [เปิดโปรแกรม (GUI)](#เปิดโปรแกรม-gui--สำหรับมือใหม่-ไม่ต้องใช้-command-line)
1. [โครงสร้างโปรเจกต์](#1-โครงสร้างโปรเจกต์)
2. [ติดตั้งและรัน](#2-ติดตั้งและรัน)
3. [การตั้งค่า (.env / config.yaml)](#3-การตั้งค่า-env--configyaml)
4. [REST API](#4-rest-api)
5. [ตัวอย่างเรียกใช้ด้วย curl และ PowerShell](#5-ตัวอย่างเรียกใช้ด้วย-curl-และ-powershell)
6. [MCP server ในตัว](#6-mcp-server-ในตัว)
7. [เชื่อมต่อ OpenCode](#7-เชื่อมต่อ-opencode)
8. [เชื่อมต่อ Cursor](#8-เชื่อมต่อ-cursor)
9. [Agent ที่รองรับ](#9-agent-ที่รองรับ)
10. [เพิ่ม agent ใหม่ผ่าน config](#10-เพิ่ม-agent-ใหม่ผ่าน-config)
11. [Build เป็น EXE ด้วย build.bat](#11-build-เป็น-exe-ด้วย-buildbat)
12. [ความปลอดภัย](#12-ความปลอดภัย)
13. [การแก้ปัญหา (Troubleshooting)](#13-การแก้ปัญหา-troubleshooting)
14. [ข้อจำกัดที่ทราบ](#14-ข้อจำกัดที่ทราบ)

---

## 1. โครงสร้างโปรเจกต์

```
ai-agent-router/
├── main.py              FastAPI app + entrypoint (ไม่มี argument = GUI; --no-gui / --mcp-stdio / --port ...)
├── gui.py               หน้าต่างโปรแกรม (Tkinter) ภาษาไทย
├── mcp_server.py        MCP server (tools: invoke_agent, delegate, list_agents)
├── router_core.py       แกนกลาง: registry ของ agent, ตรวจ API key, route ตาม target
├── config.py            โหลด .env + config.yaml, ${ENV} substitution, logging
├── agents/
│   ├── __init__.py      registry ชนิด agent แบบ lazy (AGENT_TYPES)
│   ├── base.py          BaseAgent (abstract, async) + AgentError
│   ├── http_agent.py    agent ชนิด http ทั่วไป (POST JSON ไปที่ URL)
│   ├── grok.py          xAI Grok (https://api.x.ai/v1/chat/completions)
│   ├── cursor.py        Cursor (placeholder + webhook mode)
│   └── opencode.py      OpenCode (เรียก HTTP API ของ `opencode serve`)
├── docs/                ภาพตัวอย่างหน้าจอ
├── tests/
│   ├── mock_echo_server.py   mock agent สำหรับทดสอบ
│   └── mcp_client_test.py    ทดสอบ MCP ผ่าน http / sse / stdio
├── requirements.txt
├── .env.example
├── config.yaml.example
├── build.bat            build -> dist\AI-Agent-Router.exe
└── README.md
```

---

## 2. ติดตั้งและรัน

ต้องมี **Python 3.11 – 3.13 (64-bit)** — (ผู้ใช้ทั่วไปใช้ไฟล์ EXE ได้เลย ไม่ต้องทำหัวข้อนี้)

### Windows (PowerShell / CMD)
```bat
cd ai-agent-router
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py                 :: เปิด GUI — สร้าง .env + กุญแจให้อัตโนมัติ
:: หรือแบบไม่มีหน้าต่าง (ต้องมี .env เอง):
copy .env.example .env
copy config.yaml.example config.yaml
notepad .env
python main.py --no-gui
```

### Linux / macOS
```bash
cd ai-agent-router
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config.yaml.example config.yaml     # ไม่บังคับ: ถ้าไม่มีจะใช้ agent ค่าเริ่มต้น grok / cursor / opencode
python main.py --no-gui                # หรือ python main.py เพื่อเปิด GUI (Linux ต้องมี python3-tk)
```

เปิด http://127.0.0.1:8080/health เพื่อตรวจสอบ (เอกสาร API อัตโนมัติอยู่ที่ http://127.0.0.1:8080/docs)

### ตัวเลือก command line
| ตัวเลือก | ความหมาย |
|---|---|
| `--host 0.0.0.0` | เปลี่ยน host ที่ bind (ค่าเริ่มต้น `127.0.0.1`) |
| `--port 9000` | เปลี่ยน port (ค่าเริ่มต้น `8080`) |
| `--config D:\router\config.yaml` | ระบุไฟล์ config เอง |
| `--mcp-stdio` | รันเป็น MCP server แบบ stdio (ไม่เปิด HTTP) |
| `--gui` | เปิดหน้าต่าง GUI (ค่าเริ่มต้นเมื่อไม่มี argument) |
| `--no-gui`, `--headless` | รันเซิร์ฟเวอร์โดยไม่เปิดหน้าต่าง |
| `--log-level DEBUG` | ระดับ log |
| `--log-file logs\router.log` | เขียน log ลงไฟล์ด้วย |
| `--version` | แสดงเวอร์ชัน |

---

## 3. การตั้งค่า (.env / config.yaml)

### ลำดับความสำคัญ (สูง → ต่ำ)
1. ตัวเลือก CLI (`--host`, `--port`, ...)
2. Environment variables (รวมค่าจาก `.env`) — ค่าใน environment จริงชนะค่าใน `.env`
3. `config.yaml`
4. ค่าเริ่มต้นในโค้ด

### ตำแหน่งที่ค้นหาไฟล์
`.env` และ `config.yaml` จะถูกค้นหาที่
1. **โฟลเดอร์เดียวกับ EXE** (เมื่อรันจาก `AI-Agent-Router.exe`) หรือโฟลเดอร์เดียวกับ `main.py`
2. current working directory

หรือระบุตรง ๆ ด้วย `--config` / env `ROUTER_CONFIG`
> ข้อดี: เมื่อ OpenCode / Cursor สั่งรัน `AI-Agent-Router.exe --mcp-stdio` จากโฟลเดอร์อื่น ก็ยังเจอ config ข้าง EXE

### .env (สำคัญที่สุด)
```ini
# key:agent  -> key นี้ผูกกับ agent นั้น (from_agent ต้องตรง ไม่งั้น 403)
# key อย่างเดียว -> ใช้แทน agent ไหนก็ได้
ROUTER_API_KEYS=oc-xxxxxxxx:opencode,cu-yyyyyyyy:cursor
XAI_API_KEY=xai-...........
# GROK_MODEL=grok-4.7
```
สร้าง key แบบสุ่ม: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

| ตัวแปร | ความหมาย |
|---|---|
| `ROUTER_API_KEYS` | รายการ API key คั่นด้วย `,` รูปแบบ `key:agent` |
| `ROUTER_HOST`, `ROUTER_PORT` | host/port |
| `ROUTER_LOG_LEVEL`, `ROUTER_LOG_FILE` | logging |
| `ROUTER_CONFIG` | path ของ config.yaml |
| `ROUTER_HOME` | ใช้โฟลเดอร์นี้แทนโฟลเดอร์ของ EXE สำหรับ `.env` / `config.yaml` / `logs` |
| `ROUTER_NO_GUI` | `1` = ไม่เปิด GUI แม้ไม่มี argument |
| `ROUTER_GUI_AUTOSTART` | `1`/`0` เริ่มเซิร์ฟเวอร์อัตโนมัติเมื่อเปิด GUI (ค่าเริ่มต้น 1) |
| `ROUTER_MCP_REQUIRE_AUTH` | `true`/`false` บังคับ key บน /mcp, /sse |
| `ROUTER_ALLOW_ANONYMOUS` | `true` = ไม่ต้องมี key เมื่อยังไม่ได้ตั้ง key ใดเลย (ทดสอบเท่านั้น) |
| `XAI_API_KEY`, `GROK_MODEL`, `XAI_BASE_URL` | สำหรับ Grok |
| `OPENCODE_BASE_URL`, `OPENCODE_SERVER_PASSWORD`, `OPENCODE_SERVER_USERNAME` | สำหรับ OpenCode server mode |
| `CURSOR_WEBHOOK_URL` | webhook ของ Cursor bridge |

### config.yaml
ดูตัวอย่างเต็มใน `config.yaml.example` — รองรับ `${ENV_VAR}` และ `${ENV_VAR:-ค่าเริ่มต้น}`

```yaml
server: { host: 127.0.0.1, port: 8080 }
logging: { level: INFO, file: logs/router.log }
auth:
  api_keys:
    - { key: "${OPENCODE_ROUTER_KEY}", agent: opencode }
    - { key: "${CURSOR_ROUTER_KEY}",   agent: cursor }
mcp: { enabled: true, path: /mcp, sse_enabled: true, require_auth: true }
default_from_agent: opencode
allow_self_call: false
agents:
  grok:     { type: grok, api_key: "${XAI_API_KEY}", model: grok-4.7, timeout: 120 }
  opencode: { type: opencode, base_url: "${OPENCODE_BASE_URL:-}" }
  cursor:   { type: cursor, webhook_url: "${CURSOR_WEBHOOK_URL:-}" }
```
> key จาก `ROUTER_API_KEYS` จะถูก **รวม** กับ `auth.api_keys` ใน config.yaml
> ถ้าไม่มีส่วน `agents:` เลย จะใช้ agent ค่าเริ่มต้น `grok`, `cursor`, `opencode`

---

## 4. REST API

### `GET /health` (ไม่ต้องใช้ key)
```json
{"status":"ok","app":"AI Agent Router","version":"1.0.0","auth_required":true,
 "mcp":{"enabled":true,"path":"/mcp","sse":"/sse"},
 "agents":[{"name":"grok","type":"grok","enabled":true,"configured":true}, ...]}
```
`configured` = agent มีค่าที่จำเป็นครบหรือยัง (เช่น Grok มี `XAI_API_KEY` แล้วหรือไม่)

### `GET /agents` (ต้องใช้ key) — รายละเอียด agent ทั้งหมด

### `POST /invoke` (ต้องใช้ key)
Header: `X-API-Key: <key>` (หรือ `Authorization: Bearer <key>`)
```json
{"target": "grok", "message": "รีวิวฟังก์ชันนี้ให้หน่อย", "context": {"file": "utils.py", "code": "..."}, "from_agent": "opencode"}
```
- `target` (บังคับ) ชื่อ agent ปลายทาง **หนึ่งตัว**
- `message` (บังคับ) งาน/คำสั่ง
- `context` (ไม่บังคับ) JSON object ข้อมูลประกอบ — Grok จะได้รับเป็นข้อความ system เพิ่มเติม
- `from_agent` (ไม่บังคับ) ชื่อผู้เรียก — ถ้าไม่ใส่ใช้ agent ที่ผูกกับ key หรือ `opencode`

ผลลัพธ์สำเร็จ (HTTP 200):
```json
{"target":"grok","from_agent":"opencode","response":"...คำตอบ...","status":"ok","elapsed_ms":1234.5,"request_id":"a1b2c3d4e5f60718"}
```
ผลลัพธ์ผิดพลาด (ทุกกรณีมีรูปแบบเดียวกัน + header `X-Request-ID`):
```json
{"status":"error","error":{"code":"unknown_target","message":"Unknown target agent 'x'. Registered: ..."},"request_id":"...","target":"x","from_agent":"opencode","elapsed_ms":0.1}
```

| HTTP | code | สาเหตุ |
|---|---|---|
| 400 | `self_call`, `missing_target`, `missing_message`, `bad_context` | target == from_agent / ข้อมูลไม่ครบ |
| 401 | `missing_api_key`, `invalid_api_key`, `auth_not_configured` | ไม่มี key / key ผิด / router ยังไม่ได้ตั้ง key |
| 403 | `from_agent_mismatch` | key ผูกกับ agent A แต่ส่ง from_agent เป็น B |
| 404 | `unknown_target` | ไม่มี agent ชื่อนั้น |
| 413 | `message_too_large` | message ยาวเกิน `max_message_chars` |
| 422 | `validation_error` | JSON body ไม่ถูกต้อง |
| 502 | `upstream_error`, `upstream_unreachable`, `bad_upstream_payload`, `agent_crashed` | ปลายทางตอบ error / ติดต่อไม่ได้ |
| 503 | `agent_not_configured`, `agent_disabled` | agent ยังไม่ได้ตั้งค่า (เช่นไม่มี XAI_API_KEY) / ถูกปิด |
| 504 | `upstream_timeout` | ปลายทางตอบช้าเกิน `timeout` |

ส่ง header `X-Request-ID` มาเองได้ เพื่อใช้ไล่ log ข้ามระบบ

---

## 5. ตัวอย่างเรียกใช้ด้วย curl และ PowerShell

### curl (Linux/macOS/Git Bash)
```bash
curl http://127.0.0.1:8080/health

curl -X POST http://127.0.0.1:8080/invoke \
  -H "Content-Type: application/json" \
  -H "X-API-Key: oc-xxxxxxxx" \
  -d '{"target":"grok","message":"สรุปข้อดีของ asyncio ใน 3 ข้อ","context":{"lang":"th"},"from_agent":"opencode"}'
```

### curl.exe บน Windows CMD (ต้อง escape เครื่องหมาย ")
```bat
curl.exe -X POST http://127.0.0.1:8080/invoke -H "Content-Type: application/json" -H "X-API-Key: oc-xxxxxxxx" -d "{\"target\":\"grok\",\"message\":\"hello\"}"
```

### PowerShell (Invoke-RestMethod)
```powershell
Invoke-RestMethod http://127.0.0.1:8080/health

$headers = @{ "X-API-Key" = "oc-xxxxxxxx" }
$body = @{
  target     = "grok"
  message    = "รีวิวโค้ดนี้ให้หน่อย"
  context    = @{ file = "utils.py"; code = "def add(a,b): return a+b" }
  from_agent = "opencode"
} | ConvertTo-Json -Depth 10

$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/invoke `
       -Headers $headers -ContentType "application/json; charset=utf-8" `
       -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$r.response
```
> ใช้ `UTF8.GetBytes` เพื่อให้ภาษาไทยถูกส่งเป็น UTF-8 แน่นอน (Windows PowerShell 5.1)

ดูรายการ agent:
```powershell
Invoke-RestMethod http://127.0.0.1:8080/agents -Headers @{ "X-API-Key" = "oc-xxxxxxxx" }
```

---

## 6. MCP server ในตัว

Tools ที่มีให้:
| Tool | พารามิเตอร์ | ความหมาย |
|---|---|---|
| `invoke_agent` | `target`, `message`, `context?`, `from_agent?` | ส่งงานให้ agent ที่ระบุชื่อ แล้วคืนผล (โครงสร้างเดียวกับ /invoke) |
| `delegate` | เหมือน `invoke_agent` | ชื่อเรียกแทน (alias) |
| `list_agents` | – | รายชื่อ agent ที่ลงทะเบียน |

ทุก tool เรียก router core **ภายใน process เดียวกัน** (ไม่ผ่าน HTTP ซ้ำ) — error จะถูกส่งกลับเป็น tool result ที่ `isError=true` พร้อมข้อความเช่น `[404 unknown_target] ...`

ช่องทาง (transport):
| Transport | URL / คำสั่ง | Auth |
|---|---|---|
| Streamable HTTP (แนะนำ) | `http://127.0.0.1:8080/mcp` | `X-API-Key` หรือ `Authorization: Bearer` (ปิดได้ด้วย `mcp.require_auth: false`) |
| SSE (แบบเก่า) | `http://127.0.0.1:8080/sse` (+ `/messages/`) | เหมือนกัน |
| stdio | `AI-Agent-Router.exe --mcp-stdio` หรือ `python main.py --mcp-stdio` | ไม่ต้องใช้ key (เป็น process ในเครื่องที่ client สั่งรันเอง) |

- HTTP MCP ใช้ port เดียวกับ REST (8080) — ต้องเปิด router ค้างไว้
- โหมด stdio: **stdout ใช้สำหรับ JSON-RPC เท่านั้น** log ทั้งหมดออก stderr / ไฟล์ log
- key ที่ผูก agent (เช่น `oc-xxx:opencode`) จะบังคับ `from_agent` ใน MCP ด้วย
- เมื่อ bind `127.0.0.1` SDK เปิด DNS-rebinding protection อัตโนมัติ (รับเฉพาะ Host `127.0.0.1:*`, `localhost:*`)

---

## 7. เชื่อมต่อ OpenCode

ไฟล์ `opencode.json` (ในโปรเจกต์) หรือ `~/.config/opencode/opencode.json` (global)
อ้างอิงรูปแบบ: https://opencode.ai/docs/mcp-servers/

### แบบ remote (router เปิดค้างไว้ที่ 8080) — แนะนำ
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agent-router": {
      "type": "remote",
      "url": "http://127.0.0.1:8080/mcp",
      "headers": { "X-API-Key": "oc-xxxxxxxx" },
      "oauth": false,
      "enabled": true
    }
  }
}
```
- `"oauth": false` ปิดการเดา OAuth อัตโนมัติของ OpenCode (router ใช้ API key ไม่ใช่ OAuth) — ถ้า key ผิด OpenCode จะได้ 401 ชัดเจนแทนการพยายามเปิด OAuth
- ใช้ env แทน hardcode key ได้: `"X-API-Key": "{env:AGENT_ROUTER_KEY}"`

### แบบ local (OpenCode สั่งรัน EXE เองผ่าน stdio)
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agent-router": {
      "type": "local",
      "command": ["C:\\Tools\\AI-Agent-Router\\AI-Agent-Router.exe", "--mcp-stdio"],
      "enabled": true,
      "environment": { "XAI_API_KEY": "xai-..." }
    }
  }
}
```
หรือแบบ Python: `"command": ["C:\\path\\ai-agent-router\\.venv\\Scripts\\python.exe", "C:\\path\\ai-agent-router\\main.py", "--mcp-stdio"]`

### ใช้งานใน OpenCode
พิมพ์ใน prompt เช่น
> ใช้ tool agent-router invoke_agent ส่งงานให้ target "grok": รีวิวไฟล์ src/utils.py หา bug

ตรวจสถานะ: `opencode mcp list`
(ชื่อ tool ใน OpenCode จะขึ้นต้นด้วยชื่อ server เช่น `agent-router_invoke_agent`)

---

## 8. เชื่อมต่อ Cursor

ไฟล์ `.cursor/mcp.json` (เฉพาะโปรเจกต์) หรือ `~/.cursor/mcp.json` (global)
อ้างอิง: https://cursor.com/docs/context/mcp

### แบบ remote (Streamable HTTP)
```json
{
  "mcpServers": {
    "agent-router": {
      "url": "http://127.0.0.1:8080/mcp",
      "headers": { "X-API-Key": "cu-yyyyyyyy" }
    }
  }
}
```
(ใช้ env ได้: `"X-API-Key": "${env:AGENT_ROUTER_KEY}"`) — key ของ Cursor ควรผูกกับ `cursor` เช่น `cu-yyyyyyyy:cursor` แล้วตอนเรียกให้ใส่ `from_agent: "cursor"` หรือเว้นไว้ (ระบบจะใช้ `cursor` อัตโนมัติ)

### แบบ command (stdio)
```json
{
  "mcpServers": {
    "agent-router": {
      "type": "stdio",
      "command": "C:\\Tools\\AI-Agent-Router\\AI-Agent-Router.exe",
      "args": ["--mcp-stdio"],
      "env": { "XAI_API_KEY": "${env:XAI_API_KEY}" }
    }
  }
}
```
แบบ Python: `"command": "C:\\path\\ai-agent-router\\.venv\\Scripts\\python.exe", "args": ["C:\\path\\ai-agent-router\\main.py", "--mcp-stdio"]`

ดู log ใน Cursor: Output panel → เลือก "MCP Logs"

---

## 9. Agent ที่รองรับ

| type | ไฟล์ | สถานะ | ต้องตั้งค่า |
|---|---|---|---|
| `grok` (`xai`) | `agents/grok.py` | ใช้งานได้จริง | `XAI_API_KEY`; `model` (ค่าเริ่มต้น `grok-4.7`), `timeout`, `temperature`, `max_tokens`, `system_prompt`, `base_url` |
| `http` (`webhook`) | `agents/http_agent.py` | ใช้งานได้จริง | `url`; `method`, `headers`, `response_field`, `extra_body`, `timeout` |
| `opencode` | `agents/opencode.py` | ใช้งานได้ (server mode) | `base_url` ของ `opencode serve`; `password`, `agent`, `model`, `reuse_session`, `directory` หรือ `mode: webhook` + `url` |
| `cursor` | `agents/cursor.py` | placeholder + webhook | `webhook_url` (ไม่ตั้ง = ตอบ 503 "not configured") |
| `"package.module:Class"` | ของคุณเอง | – | class ที่สืบทอด `BaseAgent` |

### Grok
ส่ง `POST https://api.x.ai/v1/chat/completions` ด้วย `Authorization: Bearer $XAI_API_KEY`
ข้อความ system = system_prompt + ชื่อ agent ผู้เรียก + `context` (JSON) ; ข้อความ user = `message`
เปลี่ยนรุ่นได้ด้วย `GROK_MODEL` ใน .env (มีผลกับ agent ชนิด grok ทุกตัว) หรือ `model:` ใน config.yaml
ดูรายชื่อรุ่นล่าสุดที่ https://docs.x.ai/docs/models

### OpenCode เป็นปลายทาง (agent อื่นสั่งงาน OpenCode)
1. รัน `opencode serve --port 4096` ในโฟลเดอร์โปรเจกต์ (ตั้ง `OPENCODE_SERVER_PASSWORD` ได้ถ้าต้องการ basic auth)
2. ตั้ง `agents.opencode.base_url: http://127.0.0.1:4096`
3. router จะเรียก `POST /session` (สร้าง session ครั้งแรก) แล้ว `POST /session/{id}/message` พร้อม `{"parts":[{"type":"text","text": message + context}]}` แล้วรวมข้อความชนิด `text` ใน reply เป็น `response`
   (ตาม https://opencode.ai/docs/server/) — `reuse_session: true` จะใช้ session เดิมต่อเนื่อง และสร้างใหม่อัตโนมัติถ้า session หาย (404)

### Cursor เป็นปลายทาง
Cursor ยังไม่มี API สาธารณะแบบ "ส่ง prompt แล้วรับคำตอบ" — adapter นี้จึงเป็น placeholder:
ถ้าตั้ง `webhook_url` router จะ POST `{"message","context","from_agent","target"}` ไปที่ URL นั้น (เช่น bridge script / n8n / Cursor background agent wrapper ที่คุณเขียนเอง) และอ่านคำตอบจาก field `response`/`output`/`text`/... ; ถ้าไม่ตั้งจะตอบ 503 พร้อมข้อความอธิบาย
(ทิศทาง Cursor → router ผ่าน MCP ใช้งานได้เต็มที่)

---

## 10. เพิ่ม agent ใหม่ผ่าน config

ไม่ต้องแก้โค้ด — เพิ่มใน `config.yaml` แล้ว restart router:
```yaml
agents:
  claude-bridge:
    type: http
    url: http://127.0.0.1:9100/invoke
    method: POST
    headers:
      Authorization: "Bearer ${CLAUDE_BRIDGE_TOKEN}"
    response_field: data.text        # dotted path ใน JSON reply (ไม่ใส่ = ลอง response/output/text/content/message/result/answer)
    timeout: 300
    description: Claude ผ่าน bridge ของฉัน
```
router จะส่ง body:
```json
{"message":"...","context":{...},"from_agent":"opencode","target":"claude-bridge"}
```
ถ้า endpoint ตอบเป็น text ธรรมดา (ไม่ใช่ JSON) จะใช้ทั้ง body เป็น response

เพิ่ม key ให้ agent ใหม่ (ถ้ามันจะเป็นผู้เรียกด้วย): `ROUTER_API_KEYS=...,cb-zzzz:claude-bridge`

ทดลองด้วย mock: `python tests/mock_echo_server.py 9001` แล้วตั้ง agent `echo: {type: http, url: http://127.0.0.1:9001/invoke}`

### เขียนชนิด agent ใหม่ (โค้ด)
```python
# my_agents/ollama.py
from agents.base import BaseAgent
class OllamaAgent(BaseAgent):
    type_name = "ollama"
    async def invoke(self, message, context=None, from_agent="opencode"):
        r = await self._request("POST", "http://127.0.0.1:11434/api/generate",
                                json={"model": self.config.get("model", "llama3"), "prompt": message, "stream": False})
        return r.json()["response"]
```
แล้วใน config.yaml: `type: "my_agents.ollama:OllamaAgent"` (ใช้ได้ตอนรันด้วย Python; ถ้าจะใช้ใน EXE ต้องเพิ่ม `--hidden-import my_agents.ollama` ใน build.bat)

> ⚠️ YAML: ชื่อ agent อย่าง `off`, `on`, `yes`, `no` ต้องใส่เครื่องหมายคำพูด (`"off":`) ไม่งั้น YAML จะแปลงเป็น true/false

---

## 11. Build เป็น EXE ด้วย build.bat

```bat
cd ai-agent-router
build.bat
```
ต้องใช้ Python 3.11 – 3.13 จาก python.org (มี tkinter มาด้วย — ตอนติดตั้งต้องติ๊ก "tcl/tk and IDLE" ซึ่งติ๊กไว้เป็นค่าเริ่มต้น)

สิ่งที่ build.bat ทำ:
1. หา Python (`py -3` หรือ `python`) แล้วสร้าง `.venv` (ถ้ายังไม่มี)
2. `pip install -r requirements.txt` (รวม PyInstaller) และตรวจว่ามี tkinter
3. `pyinstaller --onefile --console --hide-console hide-early --name AI-Agent-Router` พร้อม
   `--collect-submodules mcp.server/mcp.shared/mcp.client/mcp.types/mcp.os --collect-data mcp --copy-metadata mcp`,
   `--collect-all` สำหรับ `mcp_types fastapi starlette uvicorn sse_starlette pydantic pydantic_core httpx httpx2 anyio jsonschema jsonschema_specifications opentelemetry`,
   `--hidden-import yaml dotenv python_multipart agents.* config router_core mcp_server gui tkinter tkinter.ttk tkinter.scrolledtext tkinter.messagebox tkinter.font`
4. คัดลอก `.env.example`, `config.yaml.example` (และ `config.yaml` ถ้ามี) ไปไว้ใน `dist\` — **ไม่คัดลอก `.env`** เพราะ GUI จะสร้างให้พร้อมกุญแจใหม่ตอนเปิดครั้งแรก

ผลลัพธ์: `dist\AI-Agent-Router.exe` (~30 MB) — ย้ายไปไว้โฟลเดอร์ไหนก็ได้ (ที่เขียนไฟล์ได้) แล้วดับเบิลคลิก
```bat
dist\AI-Agent-Router.exe                 :: GUI
dist\AI-Agent-Router.exe --no-gui        :: เซิร์ฟเวอร์อย่างเดียว http://127.0.0.1:8080
dist\AI-Agent-Router.exe --mcp-stdio     :: โหมด MCP stdio
```

### ทำไมเป็น console EXE + `--hide-console hide-early` (ไม่ใช้ `--windowed`)
- โหมด `--mcp-stdio` ต้องมี stdin/stdout จริงสำหรับคุยกับ OpenCode/Cursor — EXE แบบ console มีเสมอ ไม่ขึ้นกับว่าโปรแกรมแม่ส่ง pipe มาอย่างไร ส่วน `--windowed` (GUI subsystem) บน Windows อาจไม่มี stdout/stderr (`sys.stdout` เป็น `None`) ซึ่งเสี่ยงทำให้ stdio MCP พัง
- `--hide-console hide-early`: เมื่อ **ดับเบิลคลิก** (EXE เป็นเจ้าของหน้าต่าง console เอง) bootloader ของ PyInstaller จะซ่อน console ทันทีตั้งแต่ก่อนแตกไฟล์ → ผู้ใช้เห็นแค่หน้าต่าง GUI (อาจเห็นกรอบดำแวบสั้นมากเสี้ยววินาทีบางเครื่อง)
- เมื่อเปิดจาก cmd/PowerShell ที่มีอยู่แล้ว console **ไม่ถูกซ่อน** (เพราะไม่ใช่ของ EXE) → เห็น log ตามปกติ
- `gui.py` มีตัวสำรอง (ctypes `GetConsoleProcessList` + `ShowWindow`) ซ่อน console ของตัวเองเฉพาะกรณีที่เป็นเจ้าของ เช่นเปิด `main.py` ด้วย python.exe จาก Explorer

> หมายเหตุ: **ห้ามใช้ `--collect-all mcp`** — จะ import `mcp.cli` ที่ต้องใช้แพ็กเกจ `typer` และทำให้ build ล้ม (ทดสอบแล้ว)
> คำเตือน `Failed to collect submodules for 'httpx2.websockets' ... wsproto` ระหว่าง build ไม่เป็นปัญหา (ไม่ได้ใช้ websocket)

---

## 12. ความปลอดภัย
- ค่าเริ่มต้น bind `127.0.0.1` เท่านั้น — ถ้าเปลี่ยนเป็น `0.0.0.0` ทุกเครื่องใน network เข้าถึงได้ ต้องตั้ง key ที่แข็งแรงและพิจารณา firewall
- ถ้ายังไม่ได้ตั้ง API key ใดเลย router จะ **ปฏิเสธ** ทุกคำขอ (401 `auth_not_configured`) — เว้นแต่ตั้ง `allow_anonymous: true`
- เปรียบเทียบ key แบบ constant-time, log แสดงเฉพาะ 3 ตัวแรกของ key
- ผูก key กับ agent (`key:agent`) เพื่อป้องกัน agent หนึ่งปลอมตัวเป็นอีกตัว
- อย่า commit `.env` / `config.yaml` ที่มี key จริง (มี `.gitignore` ให้แล้ว)

---

## 13. การแก้ปัญหา (Troubleshooting)

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| `401 auth_not_configured` | ยังไม่ได้ตั้ง `ROUTER_API_KEYS` ใน `.env` (หรือ `.env` ไม่ได้อยู่ข้าง EXE/main.py หรือ cwd) — ดู log บรรทัด `config: ... \| .env: ...` ตอนเริ่ม |
| `401 invalid_api_key` | key ใน header ไม่ตรงกับที่ตั้งไว้ (ระวังช่องว่าง/ขึ้นบรรทัดใหม่) |
| `403 from_agent_mismatch` | key ผูกกับ agent อื่น — ใส่ `from_agent` ให้ตรง หรือเว้นว่าง |
| `503 agent_not_configured` (grok) | ใส่ `XAI_API_KEY` ใน `.env` แล้ว restart; ตรวจ `/health` ว่า `configured: true` |
| `502 upstream HTTP 401/403` จาก Grok | `XAI_API_KEY` ผิดหรือหมดอายุ / ไม่มีสิทธิ์ใช้ model นั้น |
| `502 upstream HTTP 404` จาก Grok | ชื่อ model ไม่มีแล้ว — เปลี่ยน `GROK_MODEL` ตาม https://docs.x.ai/docs/models |
| `504 upstream_timeout` | เพิ่ม `timeout:` ของ agent นั้นใน config.yaml |
| port 8080 ถูกใช้ (`[Errno 10048]` / `address already in use`) | `--port 9000` หรือหา process: `netstat -ano \| findstr :8080` |
| OpenCode ขึ้น MCP failed / พยายามทำ OAuth | ตรวจว่า router เปิดอยู่, url ลงท้าย `/mcp`, header `X-API-Key` ถูก, และใส่ `"oauth": false` |
| OpenCode: timeout ตอน fetch tools | เพิ่ม `"timeout": 15000` ใน config ของ MCP server (ค่าเริ่มต้น 5 วินาที; EXE onefile ครั้งแรกอาจเริ่มช้า) |
| Cursor ไม่เห็น tools | Output → "MCP Logs"; ลองแบบ stdio; ตรวจ path ของ EXE ใน `command` (ต้องใช้ `\\` ใน JSON) |
| stdio client ได้ JSON เสีย | อย่าพิมพ์อะไรออก stdout ใน agent ที่เขียนเอง — ใช้ `logging` (ออก stderr) |
| `421 Misdirected` / `Invalid Host header` บน /mcp | เรียกด้วย host ที่ไม่ใช่ `127.0.0.1`/`localhost` ขณะ bind 127.0.0.1 — ใช้ `http://127.0.0.1:8080/mcp` |
| Windows Defender / SmartScreen เตือน EXE | ปกติสำหรับ EXE ที่ build เองและไม่มี signature — กด More info → Run anyway หรือ whitelist โฟลเดอร์ |
| EXE เปิดแล้วปิดทันที / ไม่มีหน้าต่าง | รันจาก CMD (`AI-Agent-Router.exe --gui`) เพื่อดู error เช่น `config error: ...` จาก YAML ผิดรูปแบบ; ดู `logs\router.log` ข้าง EXE |
| GUI: ไฟแดง "พอร์ต 8080 ถูกใช้งานอยู่" | เปิดโปรแกรมซ้ำอยู่แล้ว (ดูที่ taskbar) หรือโปรแกรมอื่นใช้พอร์ต — ใส่พอร์ตอื่นแล้วกด "บันทึกพอร์ต" แล้วอัปเดต URL ใน config ของ OpenCode/Cursor (แท็บคู่มืออัปเดตให้อัตโนมัติ) |
| GUI: "บันทึกไฟล์ไม่ได้" | ย้าย EXE ไปโฟลเดอร์ที่เขียนได้ (Desktop / Documents) |
| ภาษาไทยเพี้ยนใน PowerShell | ส่ง body เป็น UTF-8 bytes ตามตัวอย่างหัวข้อ 5 |

เปิด log ละเอียด: `python main.py --no-gui --log-level DEBUG --log-file logs\router.log` (หรือใน GUI ติ๊ก "แสดงรายละเอียดทางเทคนิค"; GUI เขียน log ลง `logs\router.log` ข้าง EXE เสมอ) — ทุกบรรทัดมี `rid=<request_id>` ให้ไล่ตามได้

---

## 14. ข้อจำกัดที่ทราบ
- **Cursor**: ยังเป็น placeholder — ต้องมี webhook/bridge ของคุณเองจึงจะเป็นปลายทางได้ (Cursor → router ผ่าน MCP ใช้ได้เต็มที่)
- **OpenCode เป็นปลายทาง**: ต้องรัน `opencode serve` แยก; คำตอบรอจนจบ (ไม่ stream); เรียก API ตามเอกสาร server ของ OpenCode ณ ต.ค. 2026 ถ้า API เปลี่ยนใช้ `mode: webhook` แทนได้
- ไม่มี streaming ของคำตอบ (รอคำตอบเต็มแล้วค่อยส่งกลับ)
- ไม่มีระบบกัน loop ข้าม agent (A→B→A) อัตโนมัติ นอกจากห้าม self-call — ให้ agent ปลายทางระวังเอง
- session ของ MCP HTTP เก็บในหน่วยความจำ — restart router แล้ว client ต้อง reconnect (OpenCode/Cursor ทำเองอัตโนมัติ)
- GUI แสดง/แก้เฉพาะกุญแจตัวแรกใน `ROUTER_API_KEYS` (กุญแจอื่นในไฟล์ยังใช้ได้ตามเดิม) และไม่มีหน้าแก้ `config.yaml` (agent ขั้นสูง เช่น webhook ของ Cursor ยังต้องแก้ไฟล์)
- ใช้ `mcp==2.3.0` (FastMCP เปลี่ยนชื่อเป็น `MCPServer` ใน SDK v2) — โค้ดรองรับ `mcp` 1.x (`FastMCP`) แบบ fallback ด้วย
