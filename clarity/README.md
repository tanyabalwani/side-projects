# Clarity

A local-first workspace for turning scattered thinking into a clear, evidence-based presentation. It guides you from a brief to a mind map, a storyline, and an editable PowerPoint built on your own template. The server runs on your computer and listens on 127.0.0.1 only.

## Run it

```bash
pip install -r requirements.txt
python3 server.py --open   # Python 3.11 or newer
```

The terminal prints a link with a one-time token. Open that link; the token becomes a session cookie. Without it every request is refused.

## The journey

| Step | What you do | What the tool does |
|---|---|---|
| Brief | Say who the audience is, what you need from them, and your one main message | Recommends a framework with reasons (reverse pyramid, Pyramid Principle, SCQA, Context-Insight-Implication-Action, Problem-Solution-Impact, What-So what-Now what, Before-After-Bridge, decision brief, three-act, workshop flow) |
| Sources and scope | Paste, upload, or link material. Choose what the AI may read | Keeps title and origin, extracts key messages, facts, decisions, actions and quotes, flags duplicates, conflicts, sensitive data and instruction-like text |
| Story board | Add existing decks (.pptx, .pdf), browse their slides by theme, role or deck, and drag the ones you want into a story | Reads text, tables and chart data from every slide. Spots near-duplicates, conflicting figures and dated content, then suggests a flow and edits against your intention or a reference deck's flow |
| Mind map | Drag, merge, split, lock, tag, comment, link | Builds proposals from your sources, runs a health check. Nothing enters the map until you accept it |
| Storyline | Pick a structure | Shows where the answer lands in each structure, drafts thesis, summary, openings, closings, appendix |
| Slides | Edit, reorder, approve, lock | Chooses a layout per message, labels every bullet (sourced, yours, AI suggestion), offers 16 editing modes with a before/after review |
| Template | Upload a .pptx or .potx | Reads layouts, colours, fonts, logos and legal lines. Exports on your masters |
| Review and export | Resolve, accept, or override issues | Runs 15 quality checks, gates export on blockers and major issues, shows exactly what the file will contain |

Alongside the journey: a facilitation workspace (agenda and timer, silent brainstorm, affinity groups, dot voting, parking lot, decisions and actions, Q&A, facilitator and participant views), a knowledge base, and a security and audit screen.

### Story board: build a story from decks you already have

Add several decks from different sources. Clarity reads every slide (text, tables, chart data, notes) and gives you three ways to browse: by theme, by role (answer, evidence, case, plan, risks, ask, appendix…), or by deck. Flags show slides with charts, tables, pictures, dated years, confidential markings, and near-duplicates in other decks. Figures that disagree across decks are listed.

Drag the slides you want into your story, or press "+ Add". Write your intention, then choose the flow to follow: a framework, or **the flow of a reference deck you like**. "Suggest flow and edits" proposes:

- a new order, with the reason for each move, and a before/after strip of slide roles;
- missing pieces (no answer, no evidence, no ask) with a button to draft a starter slide from your brief;
- edits: turn a label headline into a conclusion, remove duplicates or slides that share nothing with your intention, tighten dense slides, check dated figures.

Nothing changes until you press Apply. "Send to Slides" turns the story into editable Clarity slides that cite the deck and slide they came from. Imported decks are also project sources, so the scope rules and the review checks apply to them. Pictures, diagrams and the original look are not carried over: content is rebuilt on your template.

### Reverse pyramid

The default structure puts the answer on slide 2, then the strongest arguments in order of importance (stars and votes on the map), then evidence. Background goes to the appendix. The review flags a deck whose opening does not lead with the answer.

## Source boundaries

Before any generate action you choose one of four scopes: only what you provide; plus selected knowledge-base documents; plus all documents you may access; or no retrieval. Selected and all scopes need an explicit confirmation, and changing the selection asks again. Knowledge-base documents that are draft, expired, superseded, archived, or classified above the project are left out by default. Every slide records which sources it used and whether each is yours, internal, or external web content.

Bullets must cite a provided source. If a model returns a citation that does not exist, the bullet is demoted to "AI suggestion, not sourced", and the review flags unsupported numbers.

## AI models

| Provider | When | Where text goes |
|---|---|---|
| Built-in rules | No model configured | Nowhere |
| Ollama | A local Ollama server answers on 127.0.0.1 | Stays on this machine |
| Anthropic | `ANTHROPIC_API_KEY` is set | Leaves this machine, only after you allow it for the project |

Remote use is blocked until you tick the consent box for that project, never runs for "restricted" projects, and redacts secrets, card numbers, emails and phone numbers first. Each AI call is written to the audit log with provider, size and redaction counts. Set `CLARITY_ALLOWED_PROVIDERS` (for example `ollama,offline`) to forbid a provider outright. `CLARITY_MODEL` and `OLLAMA_MODEL` choose models.

Generation prompts carry plain-writing rules, and a linter checks slide text for stock phrasing (significance padding, "serves as", "not just X but Y", vague attribution, trailing "-ing" clauses, filler openers, em dashes, title case). It is advisory and never blocks.

## Security

- Loopback only; Host header check against DNS rebinding; session cookie (HttpOnly, SameSite=Strict); CSRF header and Origin check on every change.
- Strict CSP (`default-src 'none'`, scripts and styles from self only); no `innerHTML` anywhere in the UI.
- Uploads: extension allow-list, size caps, zip-bomb checks, rejection of macros, OLE/ActiveX, PDF scripts, executables; ClamAV is used when installed.
- Links: public http(s) only, DNS pinned to the checked address, redirects re-validated, private and metadata addresses blocked.
- Prompt injection: sources are data. Lines with instruction-like text are removed before chunking, so neither a model prompt nor the rule-based drafter can carry them into a slide.
- Knowledge folders: you add them, hidden files, keys and credential names are skipped, symlinks are not followed, broad roots such as `/` or your home are refused. `CLARITY_KB_ROOTS` restricts allowed roots.
- Encryption at rest: start with `CLARITY_PASSPHRASE` set and projects, sources, templates and the knowledge base are encrypted (Fernet, scrypt-derived key). A wrong passphrase refuses to start.
- Audit log: hash-chained, no slide text, verified on the Security screen.
- Export controls: classification marking, watermark, footer legal line, optional redaction of personal data and secrets.

## What this edition does not do

Be clear about the limits before relying on it for something they matter to:

- **Single user, one machine.** There are no accounts, single sign-on, roles, or per-document permissions. Access control is your operating system login plus file permissions. The participant view is a screen-share mode; it does not authenticate other people.
- **No live multi-user editing.** Workshop input is typed on this screen. Serving it on a network is deliberately not supported.
- **No encryption in transit** because nothing is on a network. Remote model calls use HTTPS.
- **No retention, legal-hold, or single-sign-on policy engine.** Deleting a project deletes its files.
- **Images are stored but not read.** There is no OCR; you add a description to use an image as evidence.
- **Layout fit is estimated**, not rendered. PowerPoint is the final judge; the tool flags text that cannot fit at a readable size instead of shrinking it.
- **The built-in rules are modest.** Without a model, mind maps and slides are extractive and headlines are the strongest source sentence. Connect a model for real rewriting.

## Tests

```bash
python3 tests/test_core.py
python3 tests/test_api.py
python3 tests/test_decks.py
```

They cover the consent and redaction gates, citation validation, encryption at rest, the linter, the export fit check, native chart and table output, template handling, the review gate, scope enforcement, upload and link guards, authentication, CSRF, and path traversal.

## Layout of the code

`server.py` HTTP and routes · `decks.py` deck import, organising and flow suggestions · `store.py` schema, sanitising, encryption, versions, audit · `ingest.py` and `safety.py` file and link intake and scanning · `retrieval.py` chunking, BM25, knowledge base · `ai.py` models, prompts, rule-based fallbacks · `deck.py` storyline and slide generation · `review.py` quality checks · `export.py` PPTX, DOCX, Markdown, HTML · `frameworks.py` · `style.py` · `app/` the browser UI.
