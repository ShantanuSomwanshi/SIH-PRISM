# PRISM — prototype demo video script

**Team:** localhost legends · **SIH 2026, PS 26108** · **Target length:** 5 minutes

Two columns: what is on screen, and the exact words to say. Narration is written to be
read at a normal pace — roughly 130 words a minute. Timings are cues, not a stopwatch.

---

## Before you record

- Backend running: `uvicorn backend.main:app` — check `http://127.0.0.1:8000/` shows the chunk count.
- `GROQ_API_KEY` set, `AUDIO_INPUT_ENABLED=true` in `backend/.env`.
- Frontend running: `npm run dev`, browser at 100% zoom, window maximised, bookmarks bar hidden.
- Microphone allowed for the site. Do one throwaway recording so the permission prompt does not appear on camera.
- Clear the recommendation history first, then run one query so the panel is not empty later. Or keep it empty and show it filling up live.
- Have a tender PDF ready in the file picker folder in case you want the upload shot.
- Record the screen at 1080p. Record the voice-over separately if you can — it is easier to fix a fumbled line.
- Rehearse the spoken Hindi/Marathi line once so the transcription is clean on camera.

---

## Script

| Time | On screen | Narration |
|---|---|---|
| 0:00 – 0:20 | Title card: **PRISM — Procurement Recommendation for Indian Standards**, team name, PS 26108. | "Every government tender has to quote the right Indian Standard. There are over twenty thousand of them. A procurement officer writing a tender for a sewing machine or a hand pump has to know which IS number applies, which part of it, and whether it is still current." |
| 0:20 – 0:40 | Cut to the PRISM home page. Slow scroll down the page, then back to the top. | "PRISM is a domain-specific retrieval system that answers that question. You describe what you are buying, in plain words, and it recommends the standard, with the pages it came from. It is built on eighteen BIS standards, indexed as one thousand eight hundred and forty searchable passages." |
| 0:40 – 0:55 | Point at the three inputs: the text box, the **Speak** button, the upload field. | "There are three ways in. Type the requirement. Speak it, in English or an Indian language. Or upload the tender document itself, including a scanned one." |
| 0:55 – 1:15 | Click the example chip **household zig-zag sewing machine head**. Let the search run. | "Let us start with a typed requirement — a household zig-zag sewing machine head. This is a real procurement description, and it is deliberately ambiguous." |
| 1:15 – 1:45 | The follow-up question appears with its clickable options. Hover over them without clicking. | "PRISM does not guess. It found four candidates — and they are all parts of the same standard, IS 15449. Part one is general requirements, another part is accuracy, another is durability. No amount of describing the machine separates them. So the system asks the one question that does: which aspect are you specifying? The officer never types an answer. They click an option." |
| 1:45 – 2:00 | Click an option, for example the durability or accuracy part. Result loads. | "I will pick that one. The answer narrows the candidates, and the recommendation is produced from what is left." |
| 2:00 – 2:25 | Result page. Point at **Primary Standard**, then **Why this standard**. | "Here is the primary standard, with its title and edition. Under it, the reason — and this is the important part. The wording is taken only from the passages that were retrieved. The model is not allowed to write a standard number it did not find." |
| 2:25 – 2:50 | Scroll to **Sources**. Expand a source to show the page citation. Then **Allied Standards**. | "Every claim carries its source: the standard, and the page it came from. So an officer can verify it, which is the difference between a suggestion and something you can put in a tender. Below that, allied standards — the ones this standard itself cites, from a reference graph we built by extracting cross-references." |
| 2:50 – 3:05 | Scroll to **Version Status**, **Certification Requirement**, **GeM Marketplace**. | "Version status and certification are stated as what the document says, never asserted beyond that. And where the product maps onto a GeM category, from a catalogue of nine thousand seven hundred and sixty-one categories, it is shown here — so the officer can go straight to the marketplace." |
| 3:05 – 3:20 | Scroll back to the top. Clear the text box. | "Now the part that matters for the people who actually write these tenders." |
| 3:20 – 3:50 | Click **Speak**. The button turns into the recording state with the timer. Say a Hindi or Marathi requirement out loud, for example: "कैंटीन के लिए चपाती बनाने की मशीन चाहिए". Click to stop. | "Many procurement officers are more comfortable describing a requirement in their own language. So I will simply say it — in Hindi." (pause, speak the line, stop the recording) |
| 3:50 – 4:15 | "Transcribing…" appears, then **You told PRISM:** shows the English text, then the result. | "The speech goes to Whisper, which detects the language and returns English in one step. Everything after that is the same pipeline — the same search, the same clarifier, the same grounded answer. Voice is an entry point, not a separate system." |
| 4:15 – 4:35 | Click **Recommendation history** in the header. Show the saved entries, hover a **re-check** action. | "Past recommendations are kept, so an officer can come back to a tender they wrote last month and re-check whether the standard they cited has been revised." |
| 4:35 – 4:50 | Cut to the architecture diagram, full screen. Hold it. | "Under the hood: hybrid retrieval — dense embeddings and BM25, fused and reranked by a cross-encoder — then the clarifier, then a language model that can only choose from what was retrieved, then enrichment from the reference graph and the GeM catalogue." |
| 4:50 – 5:00 | Diagram still up, or back to the result page. End card with team name. | "On our evaluation set of seventy-two queries, the correct standard is first eighty-six per cent of the time, and in the top three ninety-six per cent of the time. PRISM, from team localhost legends. Thank you." |

---

## If you need to cut it shorter

Drop in this order:

1. The history and re-check shot (0:20).
2. The version status / GeM shot (0:15).
3. The architecture line, shortened to one sentence (0:10).

## If you have room to add

- **Tender upload:** upload a tender PDF and let it recommend from the document. Say: "The problem statement also allows the tender document itself as input. A scanned tender is OCR'd on the server, and searched in passages, so a tender covering several items can surface several standards."
- **A second query that is not ambiguous**, to show that the system does not always ask: "Describe it precisely and there is nothing to clarify — it answers straight away."

## Lines worth keeping honest

Judges tend to reward these, and they are true of the build:

- "It picks only from what it retrieved." — the model is constrained to the retrieved passages.
- "Every answer carries page citations."
- "It asks rather than guesses, at most twice, and only when the candidates genuinely disagree."
- "The BIS status collector — the scraper that watches for revised and withdrawn standards — is built and running, but it is not yet wired into the recommendation engine. That is the next step." (Say this if asked. Do not claim live BIS status in the demo.)
