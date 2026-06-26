# RLab Cortex — Business Plan & GTM

> Status: founding doc, May 2026. This is the playbook to take RLab Cortex from the MVP we just built to $1M ARR in 12 months and a $15M+ post seed round.

## 1. The bet

A vertically-positioned data-analysis agent — starting in **battery test** — will win where horizontal "AI for your CSV" tools lose, because:

1. The pain is acute and specific (multi-vendor data + custom domain algorithms)
2. The buyer is rich ($90–160k base salaries; $200/seat/mo barely registers)
3. The incumbent set is fragmented (Voltaiq <$15M raised in 10 years; Galvanalyser/BattETL/BEEP are OSS-only; MATLAB+Excel is the practical default)
4. The data-fragmentation problem is structural (vendors won't fix interop because lock-in is the strategy)

See [positioning.md](positioning.md) for the full white-space argument.

## 2. Pricing & packaging

Built around the 2026 industry pattern (Bessemer, Getmonetizely): **hybrid seat + credit, BYOK as enterprise unlock**.

| Tier | $/mo | What's in it | Target |
|---|---|---|---|
| **Free** | $0 | 50 runs/mo · built-in library · BYOK supported · single user | Funnel — every battery PhD on LinkedIn |
| **Pro** | $39/seat | 2,000 runs/mo · AI-codegen · save/version custom algorithms · result history · BYOK optional (we keep 30% margin if we host the tokens) | Solo engineers · small labs |
| **Team** | $99/seat (min 5) | Shared algorithm library · scheduled runs · SSO-lite · audit logs · priority sandbox queue | Lab / department |
| **Enterprise** | from $40k/yr | VPC/on-prem · SSO/RBAC · vertical algorithm packs · designated solutions engineer · SLA | OEMs · big cell makers · F500 |

**Why not pure seat?** Bessemer's 2026 data shows pure-seat has fallen from 21% to 15% of the SaaS market; hybrid is now 41% and growing. Pure seat scares enterprise procurement because "what if we scale to 50 users". Pure usage scares them because "what if it explodes". Hybrid lets us anchor predictable revenue with seats and capture upside with credits.

**Why BYOK?** GitHub Copilot's BYOK launch (Nov 2025) and Kinde's BYOK pricing model both prove BYOK shortens enterprise procurement by ~2× by removing the "token bill could explode" risk.

**Vertical algorithm packs** as paid add-ons (Battery Pack +$30/seat, CAE Pack +$30/seat, NVH Pack +$30/seat). Sold like JetBrains plugin packs.

## 3. Distribution & GTM

### Stage 0 — first 5 design partners (now → Q3 2026)

- **Channel:** founder-led LinkedIn outreach + battery / CFD / NVH conferences (AABC, ECS, Battery Show, AUTOSAR-AT, NVH Asia).
- **Offer:** $20k–$40k design-partner program (heavily discounted enterprise tier). 90-day onboarding with weekly sync; we instrument every user correction as a future training signal.
- **Goal:** 5 logos, 3 written case studies, 1 named reference (the most-respected battery test engineer in the program).

### Stage 1 — bottom-up PLG via OSS + content (Q3 2026 → Q1 2027)

- **OSS:** open-source the **Algorithm SDK** + 10 reference algorithms under Apache-2.0. Goal: 1k GitHub stars in 90 days. This is the funnel — analogue to dbt's playbook.
- **Content moat:** weekly "algorithm spotlight" blog (Mandarin + English) on dV/dQ vs ICA, sensitivity-analysis benchmarks, Savgol vs Butterworth for cycler data. Cross-post to 知乎, LinkedIn, dev.to.
- **Demo videos:** YouTube + Bilibili. 5–8 min walkthroughs of real battery / CAE workflows.
- **Community:** Discord server for OSS users. Convert active contributors into design-partner leads.

CAC target: $500 for Pro signup; $3k for Team activation; $20k for Enterprise (because Enterprise is sales-led).

### Stage 2 — marketplace + partnerships (Q1 2027 → Q3 2027)

- **AWS Marketplace** listing first (largest, most mature) — unlocks committed-spend purchasing for enterprise.
- **Alibaba Cloud + Tencent Cloud Marketplace** for the China battery market (CATL, BYD, EVE; ~50% of global cell shipments).
- **GCP Marketplace** later (best AI-buyer concentration, fewer competitors).
- **Partnerships:** Maccor / Arbin / Neware referral deals — "we make their software more useful, not compete with them."

## 4. Forecast — 12-month path to $1M ARR

| Bucket | Count | $/yr/logo | Sub-total |
|---|---|---|---|
| Pro (self-serve) | 200 seats | $468 | $94k |
| Team | 30 accounts × 8 seats avg | $9,500 | $285k |
| Design partners (Enterprise) | 5 logos | $30k | $150k |
| Marketplace-closed Enterprise | 3 logos | $150k | $450k |
| **Total ARR** | | | **~$979k** |

Achievable if:

- We close 5 design partners in Q3 2026 (≈70% confidence given the wedge)
- OSS hits 1k stars by end Q4 2026 (industry baseline ~6 mo for a focused tool)
- 1 of the design partners converts to a $150k enterprise contract in Q1 2027
- Marketplace listings are live by end Q1 2027

## 5. Fundraising plan

### Seed — target Q2 2027

- **Round size:** $3–5M
- **Post-money target:** $15–20M (consistent with 2026 hot-AI-seed comps: median $40–45M post on $10M at the highest end, more typical $15–25M for vertical AI plays without the meme bump)
- **Lead profile:** US deep-tech / vertical-SaaS specialist (a16z deep-tech, Fifth Down, Foundation, Calibrate, plus Asia: Sequoia China, Five Capital, Hongtai). One named-brand lead + 2–3 angels who are battery industry insiders (e.g. ex-CATL CTO, ex-Tesla cell ops).
- **What we'll show:**
  - $500k–$1M ARR
  - 5–10 enterprise logos including 2 named brands
  - NDR >120% (showing land-and-expand works on this wedge)
  - 50%+ design-partner contract renewal
  - Feedback-loop data: AI-codegen success rate trending up month over month → defensible moat thesis
  - One open Battery Pack + one in-flight CAE Pack (proving the vertical-replication playbook)

### What kills the round

Per WePitched / Sky9 / Bessemer 2026 founder surveys, the deal-killers are:

- "GPT wrapper" with no proprietary data → we counter with curated library + user-uploaded algorithm graveyard
- Task-Completion Rate <85% on real tasks → we instrument from day 1 in the design-partner program
- Horizontal positioning ("AI for everyone's data") → we are explicitly vertical
- Pure seat pricing → we ship hybrid
- Zero retention data after 90 days → design-partner program closes this gap
- Reliance on a single model provider → we ship multi-provider (DeepSeek default, BYOK Anthropic/OpenAI/Ollama)

## 6. Team & hiring plan

| Role | When | Why |
|---|---|---|
| Founder/CEO | now | Domain + sales |
| Founder/CTO | now | Backend + sandbox + agent orchestration (this codebase) |
| Founding designer | Q3 2026 | Product surface — the algorithm library deserves real UX |
| Domain SME — battery | Q4 2026 | The Battery Pack's curator, owns the algorithm catalog quality bar |
| Sales engineer #1 | Q1 2027 (after first $30k+ logo) | Enterprise demos + design-partner success |
| Domain SME — CAE | Q2 2027 | The CAE Pack curator |
| AE #1 | Q3 2027 | Pipeline coverage as marketplace flows kick in |

Burn target: <$120k/mo through end of seed runway (~15 months of $5M seed at average $300k/mo blended through Q4 2027).

## 7. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cycler vendors block / partner shop us out | Medium | Open ETL parsers as OSS first → community owns the protocol; vendors can't block community |
| LLM costs spike | Low (BYOK absorbs it) | Hard cap on free tier; BYOK in Pro; surcharge model in Team |
| Open-source clones | Medium-high | Moat is the curated library + the feedback loop, not the code. Encourage clones to validate market |
| Compliance (battery data is sometimes export-controlled) | High in defense / aerospace battery | VPC / on-prem from Enterprise day 1; no model fine-tuning on customer data without explicit opt-in |
| China-export friction | Medium | China deployment runs entirely on Aliyun/Tencent; US deployment on AWS. Two stacks, same code |
| AI category cools | Medium | Vertical SaaS valuations have been more stable than horizontal AI in 2025–2026 cycle |

## 8. The next 30 days

1. Ship a public landing page + waitlist (this codebase is the foundation — `npm run build && bash deploy/deploy.sh`)
2. Cold-DM 50 battery test engineers on LinkedIn. Goal: 8 demo calls, 2 paid design partners signed
3. Open-source the Algorithm SDK on GitHub with 5 reference algorithms — start the GitHub-stars funnel
4. Set up Plausible analytics + a Slack-bot pipeline for new-signup notifications (so founders can DM every signup within 5 minutes)
5. First "algorithm spotlight" blog post: "Why Savgol beats moving average for cycler voltage smoothing" — publish to LinkedIn + 知乎
