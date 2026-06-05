# Numetrix — Product Positioning & Market Research

> Status: founding doc, May 2026. Sources are cited inline. Update after each pricing experiment or design partner closes.

## TL;DR

Numetrix is the **verifiable data-analysis agent for engineers and scientists who need to trust the number** — starting with battery test engineers, then expanding to CAE post-processing and NVH/test labs. The wedge isn't "another chat-with-CSV"; it's "the AI-native MATLAB toolbox with a sandboxed plug-in marketplace".

## 1. Why generic AI data tools don't win this segment

The category leaders all converge on the same product shape: "upload a CSV → chat → LLM writes pandas → answer". Julius ($35–$450/mo, 2M users, ~$15M ARR), Hex (~$36/editor/mo, ~$20M ARR, $172M raised), ChatGPT Advanced Data Analysis, Claude Analysis, Microsoft Data Formulator, PandasAI (~24k stars), and a long YC tail.

**The #1 complaint across G2, Reddit, and HN for every one of them:**

> "Looks confident, wrong number." — recurring G2 review pattern for Julius, Hex, Tableau Pulse, Deepnote, ChatGPT ADA.

**Why this happens:** the LLM regenerates throwaway pandas each session; nothing is curated, nothing is versioned, no algorithm carries its assumptions / units / known failure modes.

Vanna AI (text-to-SQL leader) was **archived in March 2026** — the surest signal that pure NL→pandas/SQL is no longer defensible. Base models do it well enough to commoditize the layer above.

## 2. White space we are aiming at

Three crossings make a market underserved:

1. **Domain-heavy data** (sensor / instrument / simulation / time-series), not generic business tables
2. **Custom in-house algorithms** are part of the workflow — engineers have MATLAB scripts they trust more than any chatbot
3. **Trust matters more than speed** — a "looks correct" answer is worse than no answer when the cell ships to a customer or the design freezes

No incumbent serves all three. ChatGPT/Julius/Hex serve generic analysts. Tableau/ThoughtSpot/AnswerRocket serve BI buyers. SasAgent (academic) and ChartEng (single-purpose) prove the demand but don't productize. Pure-OSS battery tools (Galvanalyser, BattETL, BEEP, Batalyse) handle only the data-ETL slice — no agent, no UI, no algorithm library.

## 3. Target persona

| Persona | Why now | Pay-band | What we replace |
|---|---|---|---|
| **Battery test engineer (V1 wedge)** | 100+ gigafactories being built 2025–2030; multi-vendor cycler-data fragmentation is structural and won't fix itself | $96–$153k US base salary, easily $200/seat | Excel + MATLAB + ad-hoc Python notebooks + nCode for fatigue |
| CAE/CFD engineer | DoE/parametric studies grew with cheap cloud compute; ParaView and Tecplot don't address parametric workflows | $90–$150k US base | PyFoam + Tecplot scripts + PowerPoint stitching |
| NVH/durability test engineer | Tribal MATLAB toolboxes everywhere; Simcenter Testlab is hated | $115–$161k US base | Simcenter Testlab + MATLAB + nCode GlyphWorks |

**V1 launch persona: Battery Test Engineer at a Tier-1 OEM, cell manufacturer, or ESS integrator.**

## 4. Buyer's journey we design for

1. **Trigger:** engineer is wrestling with multi-vendor cycler exports for a new chemistry run.
2. **Search:** they Google "Maccor + Arbin + Neware unify Python", find a Numetrix blog post.
3. **Free trial:** drag-and-drop their .res / .mims / .ndax files. Numetrix unifies + computes dV/dQ + ICA + capacity-fade fit out of the box. Takes 90 seconds.
4. **Aha moment:** "this is what our PhD's MATLAB script does, except shareable and versioned."
5. **Upgrade:** team plan — they drop in their *internal* dV/dQ peak-tracker, sandbox-tested, now a team-wide callable tool. They stop emailing Jupyter notebooks.
6. **Land+expand:** lab → R&D dept → battery analytics platform team. Enterprise contract for VPC + custom algorithm pack.

## 5. Defensibility (the "wait, what's the moat?" question)

1. **Curated algorithm library** — domain-vetted, citable, with explicit assumptions, units, and uncertainty surfacing. Hard to clone without our SME team.
2. **User-uploaded algorithm graveyard turned alive** — every team's tribal MATLAB script becomes a reusable, sandboxed, versioned tool with one upload. Switching cost = N years of internal IP that now only runs on us.
3. **Vertical algorithm packs** — premium-priced bundles ("Numetrix Battery Pack", "Numetrix CAE Pack") — vetted by domain SMEs we hire later.
4. **Feedback loop** — every approved algorithm + every user correction trains our prompt library; the AI-codegen success rate compounds for *this* vertical, which generic chatbots can't match.

## 6. Roadmap

| Quarter | Milestone |
|---|---|
| **Q2 2026** | This document. MVP: 20 built-in algorithms, sandboxed code, AI-codegen, chat agent, BYOK, Docker deploy. **DONE.** |
| Q3 2026 | Battery Pack v1: Maccor/Arbin/Neware parsers, dV/dQ + ICA + GITT solvers; 5 design partners signed |
| Q4 2026 | Team plan GA; shared algorithm library; first paid customers; scheduled runs; Postgres + S3 swap-in |
| Q1 2027 | CAE Pack v1 (OpenFOAM/Fluent parsers, DoE post-processing); AWS / Aliyun marketplace listing |
| Q2 2027 | Enterprise pack (VPC / SSO / audit log); 10 paid logos; raise seed at $15–20M post |
| Q3+ 2027 | NVH Pack v1; second vertical to >$100k ARR; expand sales motion |

## 7. What we explicitly do NOT do

- General-purpose business BI (lose to Tableau/ThoughtSpot)
- Text-to-SQL (commoditized — Vanna's archival is the canary)
- Notebook IDE (lose to Hex/Deepnote)
- Generic "AI data analyst" positioning (lose to Julius)
- LLM-only output without a sandboxed test (this is the *bug* we're fixing in the category)
- Marketplace rev-share on user-contributed algorithms (no precedent works — Kaggle, HF, Replicate all proved this)

## 8. Cited sources

- Julius pricing & ARR: https://julius.ai/pricing · https://techcrunch.com/2025/07/28/ai-data-analyst-startup-julius-nabs-10m-seed-round/
- Hex pricing & funding: https://hex.tech/pricing/ · https://hex.tech/blog/series-c/
- Vanna AI archival: https://github.com/vanna-ai/vanna (status: archived March 2026)
- PandasAI: https://github.com/sinaptik-ai/pandas-ai
- Microsoft Data Formulator: https://github.com/microsoft/data-formulator
- Battery analytics market: https://www.startus-insights.com/innovators-guide/battery-analytics-companies/ · https://tracxn.com/d/trending-business-models/startups-in-battery-analytics-software/
- Galvanalyser pain quote: https://arxiv.org/abs/2010.14959
- CAE market: https://www.grandviewresearch.com/industry-analysis/computer-aided-engineering-cae-market
- CFD-online "post-processing is tedious" thread: https://www.cfd-online.com/Forums/paraview/228554-how-automate-paraview-postprocessing-using-python-script.html
- Test data management market: https://www.verifiedmarketresearch.com/product/test-data-management-market/
- AI hallucinations in analytics (Deloitte 38% stat, Databox synthesis): https://databox.com/how-to-prevent-ai-hallucinations
- 2026 SaaS pricing direction: https://www.bvp.com/atlas/the-ai-pricing-and-monetization-playbook
- Pre-seed/seed AI valuations 2026: https://techcrunch.com/2026/03/31/its-not-your-imagination-ai-seed-startups-are-commanding-higher-valuations/
