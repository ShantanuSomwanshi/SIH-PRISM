import React, { useState } from 'react';

const API_URL = 'http://127.0.0.1:8000/api/recommend';
const UPLOAD_URL = 'http://127.0.0.1:8000/api/recommend/upload';

// Sent as X-API-Key when the backend has API_KEY set. Vite only exposes
// variables beginning with VITE_, and anything it exposes ends up inside
// the JavaScript the browser downloads - so this is NOT a secret. It
// stops casual use of an exposed server; it does not hide the key from
// anyone who opens developer tools. A production portal would call this
// API from its own server, where a real secret can be kept.
const API_KEY = import.meta.env.VITE_PRISM_API_KEY || '';

const authHeaders = () => (API_KEY ? { 'X-API-Key': API_KEY } : {});

// Every dimension the backend can ask about. Sending all of them as
// "already asked" is how the Skip button says "stop asking and answer".
const ALL_DIMENSIONS = ['part', 'role', 'product'];

// Three visible states, not two. A "medium" answer used to look identical
// to a high-confidence one because the badge simply disappeared.
const CONFIDENCE_STYLES = {
  high: {
    label: 'High confidence',
    note: 'Grounded in the retrieved standards',
    className: 'bg-green-50 text-green-800 border-green-200',
  },
  medium: {
    label: 'Medium confidence',
    note: 'Plausible, but verify before using in a tender',
    className: 'bg-amber-50 text-amber-800 border-amber-200',
  },
  low: {
    label: 'Low confidence',
    note: 'Treat as a starting point only',
    className: 'bg-red-50 text-red-700 border-red-200',
  },
};

// Examples that exercise the corpus actually indexed. The previous set
// ("antimony oxide for paints", "fuel pump diaphragm fabric") came from
// the earlier ten-document corpus and no longer matches anything, so every
// demo button failed. The first one deliberately triggers the Part
// question - it matches all four parts of IS 15449 equally well.
const EXAMPLES = [
  'household zig-zag sewing machine head',
  'chapati making machine for a canteen kitchen',
  'deepwell hand pump for a village water supply',
  'dc charging station for electric buses',
];

// Render [PLACEHOLDER] blanks visibly. An officer scanning a draft needs
// to find every gap at a glance; a placeholder set in the same colour as
// the prose is a gap that ships.
function ClauseText({ text }) {
  const parts = String(text || '').split(/(\[[^\]]+\])/g);
  return (
    <p className="text-gray-700 leading-relaxed">
      {parts.map((part, idx) =>
        part.startsWith('[') && part.endsWith(']') ? (
          <mark
            key={idx}
            className="bg-yellow-100 text-yellow-900 border border-yellow-300 rounded px-1 font-medium not-italic"
          >
            {part}
          </mark>
        ) : (
          <React.Fragment key={idx}>{part}</React.Fragment>
        )
      )}
    </p>
  );
}

export default function App() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState('');

  // Cross-questioning state. The API is stateless across rounds, so the
  // browser is what remembers the conversation: which answers have been
  // given, and which dimensions have already been put to the officer.
  const [answers, setAnswers] = useState([]);
  const [asked, setAsked] = useState([]);
  const [picked, setPicked] = useState([]);      // current multi-select
  const [copied, setCopied] = useState(false);

  const runRequest = async (request, busyLabel) => {
    setLoading(busyLabel);
    setResult(null);
    setError(null);
    setPicked([]);
    setCopied(false);
    try {
      const res = await request();
      if (!res.ok) {
        let detail = 'Request failed with status ' + res.status;
        try {
          const body = await res.json();
          if (typeof body.detail === 'string') detail = body.detail;
          else if (body.detail) detail = JSON.stringify(body.detail);
        } catch {
          /* response was not JSON - keep the status message */
        }
        throw new Error(detail);
      }
      setResult(await res.json());
    } catch (err) {
      setError(
        err.message === 'Failed to fetch'
          ? 'Could not reach the PRISM API at 127.0.0.1:8000. Check that the backend is running (uvicorn backend.main:app --reload).'
          : err.message
      );
    } finally {
      setLoading(false);
    }
  };

  const post = (text, nextAnswers, nextAsked, busyLabel) =>
    runRequest(
      () =>
        fetch(API_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({
            query: text,
            answers: nextAnswers,
            asked: nextAsked,
          }),
        }),
      busyLabel
    );

  const handleUpload = (selected) => {
    if (!selected) return;
    setFileName(selected.name);
    setQuery('');
    setAnswers([]);
    setAsked([]);
    const form = new FormData();
    form.append('file', selected);
    // No Content-Type header - the browser sets the multipart boundary.
    runRequest(
      () => fetch(UPLOAD_URL, { method: 'POST', headers: authHeaders(), body: form }),
      'Reading document...'
    );
  };

  // A fresh search. Any answers from a previous question belonged to a
  // previous description and must not be carried over - that would narrow
  // the new search to standards the officer chose for a different item.
  const handleSearch = (textToSearch) => {
    const searchText = (textToSearch ?? query ?? '').trim();
    if (!searchText) return;
    setFileName('');
    setAnswers([]);
    setAsked([]);
    post(searchText, [], [], 'Searching standards...');
  };

  // Answering keeps the ORIGINAL description and adds what was chosen.
  const answerWith = (chosen) => {
    const nextAnswers = [...answers, ...chosen];
    // The server tells us which dimensions are now covered. Falling back to
    // adding the current question's id matters: without it, a backend that
    // does not return `asked` would be asked the same question forever.
    const nextAsked = result?.asked?.length
      ? result.asked
      : [...asked, ...(question ? [question.id] : [])];
    setAnswers(nextAnswers);
    setAsked(nextAsked);
    post(query.trim(), nextAnswers, nextAsked, 'Narrowing down...');
  };

  const skipQuestions = () => {
    setAsked(ALL_DIMENSIONS);
    post(query.trim(), answers, ALL_DIMENSIONS, 'Finding the best match...');
  };

  const togglePick = (option) => {
    setPicked((current) =>
      current.some((o) => o.label === option.label)
        ? current.filter((o) => o.label !== option.label)
        : [...current, option]
    );
  };

  const draftAsText = (draft) =>
    (draft?.clauses || [])
      .map((c, i) => `${i + 1}. ${c.heading.toUpperCase()}\n${c.text}`)
      .join('\n\n') + `\n\n${'-'.repeat(60)}\n${draft?.caveat || ''}`;

  const copyDraft = async () => {
    try {
      await navigator.clipboard.writeText(draftAsText(result.tender_draft));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const confidence =
    CONFIDENCE_STYLES[result?.confidence] || CONFIDENCE_STYLES.low;
  const usedOcr = result?.sources?.some((s) => s.ocr);
  const question = result?.questions?.[0];
  const gem = result?.gem_categories;
  const draft = result?.tender_draft;

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 font-sans">
      <div className="bg-white border-b px-8 py-2 flex justify-between text-xs text-gray-600">
        <span>Government of India portal concept</span>
        <span>English</span>
      </div>

      <header className="bg-white border-b px-8 py-4 flex justify-between items-center shadow-sm">
        <div>
          <h1 className="text-xl font-bold text-red-900 tracking-wide">Manak Sahayak</h1>
          <p className="text-xs text-gray-500">Procurement Recommendation for Indian Standards</p>
        </div>
        <nav className="flex space-x-6 text-sm font-medium text-gray-700">
          <span className="cursor-pointer hover:text-red-900">Home</span>
          <span className="cursor-pointer text-red-900 border-b-2 border-red-900 pb-1">Standards</span>
          <span className="cursor-pointer hover:text-red-900">Certification</span>
        </nav>
      </header>

      <main className="max-w-4xl mx-auto py-10 px-4">
        <div className="flex justify-between items-start mb-6">
          <div>
            <span className="text-xs font-semibold text-red-800 uppercase tracking-wider">BIS Digital Service Module</span>
            <h2 className="text-2xl font-bold text-gray-900 mt-1">
              PRISM - Procurement Recommendation for Indian Standards Matching
            </h2>
            <p className="text-sm text-gray-600 mt-1">
              Describe a product or paste a tender specification to identify applicable Indian Standards.
            </p>
          </div>
          <span className="bg-amber-50 text-amber-800 text-xs px-2.5 py-1 rounded border border-amber-200 whitespace-nowrap">
            Demo data - MVP
          </span>
        </div>

        {/* Input */}
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Describe the product or paste your specification
          </label>
          <textarea
            className="w-full border border-gray-300 rounded p-3 text-sm focus:outline-none focus:ring-2 focus:ring-red-900/20 focus:border-red-900"
            rows="4"
            placeholder="e.g. household zig-zag sewing machine head, or a d.c. charging station for an electric bus depot"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSearch();
            }}
          />

          <div className="mt-4 flex items-center justify-between">
            <button
              onClick={() => handleSearch()}
              disabled={Boolean(loading)}
              className="bg-red-800 hover:bg-red-900 disabled:bg-gray-400 text-white text-sm font-medium px-5 py-2.5 rounded shadow-sm transition-colors"
            >
              {loading || 'Find Standards'}
            </button>
            <span className="text-xs text-gray-400">Ctrl+Enter to search</span>
          </div>

          <div className="mt-4 pt-4 border-t flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span>Try an example:</span>
            {EXAMPLES.map((item) => (
              <button
                key={item}
                onClick={() => { setQuery(item); handleSearch(item); }}
                className="border border-gray-300 px-2 py-1 rounded hover:bg-gray-100 text-gray-700"
              >
                {item}
              </button>
            ))}
          </div>

          {/* Upload - the problem statement asks for tender DOCUMENTS as an
              input, not just typed text. Scanned PDFs are OCR'd server-side. */}
          <div className="mt-4 pt-4 border-t">
            <label className="block text-sm font-semibold text-gray-700 mb-2">
              Or upload a sample tender document
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <label className="cursor-pointer bg-white border border-gray-300 hover:bg-gray-100 text-gray-700 text-sm px-4 py-2 rounded">
                Choose file
                <input
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  className="hidden"
                  disabled={Boolean(loading)}
                  onChange={(e) => {
                    handleUpload(e.target.files?.[0]);
                    e.target.value = '';   // allow re-picking the same file
                  }}
                />
              </label>
              {fileName && (
                <span className="text-xs text-gray-600 truncate max-w-xs">{fileName}</span>
              )}
              <span className="text-xs text-gray-400">
                PDF, Word, or text. Scanned PDFs are read with OCR, which takes longer.
              </span>
            </div>
          </div>
        </div>

        {/* Errors - previously these were only logged to the console, so a
            failed request looked exactly like nothing happening. */}
        {error && (
          <div className="mt-6 bg-red-50 border border-red-300 p-4 rounded-lg">
            <p className="text-sm font-semibold text-red-900">Request failed</p>
            <p className="text-sm text-red-800 mt-1">{error}</p>
          </div>
        )}

        {/* What has already been answered. Without this the officer loses
            track of what the narrowed result is actually based on. */}
        {answers.length > 0 && (
          <div className="mt-6 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-gray-500">You told PRISM:</span>
            {answers.map((a, idx) => (
              <span
                key={idx}
                className="bg-white border border-gray-300 text-gray-700 px-2 py-1 rounded"
              >
                {a.label}
              </span>
            ))}
            <button
              onClick={() => handleSearch()}
              className="text-red-800 underline hover:text-red-900"
            >
              start over
            </button>
          </div>
        )}

        {/* Cross-questioning */}
        {result?.clarification_needed && (
          <div className="mt-4 bg-amber-50 border border-amber-300 p-5 rounded-lg">
            <p className="text-sm font-semibold text-amber-900">
              {question ? question.question : result.message}
            </p>

            {/* Why this is being asked. A question without a reason reads
                as the system failing; with one, it reads as the system
                knowing something the officer does not. */}
            {question?.why && (
              <p className="text-xs text-amber-800 mt-1 mb-3 italic">{question.why}</p>
            )}
            {!question && (
              <p className="text-xs text-amber-800 mt-1 mb-3">{result.message}</p>
            )}

            {question ? (
              <>
                <div className="grid gap-2 sm:grid-cols-2">
                  {question.options.map((opt) => {
                    const isPicked = picked.some((o) => o.label === opt.label);
                    return (
                      <button
                        key={opt.label}
                        onClick={() =>
                          question.allow_multiple ? togglePick(opt) : answerWith([opt])
                        }
                        className={
                          'text-left border rounded px-3 py-2 transition-colors ' +
                          (isPicked
                            ? 'bg-red-800 border-red-800 text-white'
                            : 'bg-white border-amber-400 text-amber-900 hover:bg-amber-100')
                        }
                      >
                        <span className="block text-xs font-semibold">{opt.label}</span>
                        {opt.detail && (
                          <span className="block text-[11px] opacity-80 mt-0.5">
                            {opt.detail}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-3">
                  {question.allow_multiple && (
                    <button
                      onClick={() => answerWith(picked)}
                      disabled={picked.length === 0 || Boolean(loading)}
                      className="bg-red-800 hover:bg-red-900 disabled:bg-gray-300 text-white text-xs font-medium px-4 py-2 rounded"
                    >
                      Continue{picked.length ? ` (${picked.length} selected)` : ''}
                    </button>
                  )}
                  <button
                    onClick={skipQuestions}
                    disabled={Boolean(loading)}
                    className="text-xs text-amber-900 underline hover:text-amber-700"
                  >
                    Not sure - show me the best match anyway
                  </button>
                  {question.allow_multiple && (
                    <span className="text-[11px] text-amber-700">
                      Select more than one if several apply.
                    </span>
                  )}
                </div>
              </>
            ) : (
              /* Fallback for the old flat option list, so an older backend
                 still works against this page. */
              <div className="flex flex-wrap gap-2">
                {result.clarification_options?.map((opt) => (
                  <button
                    key={opt}
                    onClick={() => { setQuery(opt); handleSearch(opt); }}
                    className="bg-white border border-amber-400 px-3 py-1.5 rounded text-xs font-medium text-amber-900 hover:bg-amber-100 text-left"
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}

            {result.sources?.length > 0 && (
              <p className="mt-3 text-xs text-amber-800">
                Considered: {[...new Set(result.sources.map((s) => s.standard_id))].join(', ')}
              </p>
            )}
          </div>
        )}

        {/* Recommendation */}
        {result && !result.clarification_needed && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex justify-between items-start border-b pb-3 mb-4 gap-4">
              <h3 className="font-bold text-gray-900 text-base">Recommendation Summary</h3>
              <div className="text-right">
                <div className={'text-xs px-2.5 py-1 rounded border font-medium inline-block ' + confidence.className}>
                  <div>{confidence.label}</div>
                  <div className="font-normal opacity-80">{confidence.note}</div>
                </div>
                {/* Why the rating was held back. A capped badge that does
                    not say why reads as an ordinary "medium" and hides the
                    fact that the officer skipped a question. */}
                {result.confidence_note && (
                  <p className="text-[11px] text-amber-800 mt-1 max-w-xs">
                    {result.confidence_note}
                  </p>
                )}
              </div>
            </div>

            <div className="space-y-4 text-sm">
              <div>
                <span className="font-semibold text-gray-700">Primary Standard</span>
                <p className="text-red-900 font-medium text-base">
                  {result.primary_standard}
                </p>
                <p className="text-gray-600">{result.title}</p>
              </div>

              {result.reasoning && (
                <div>
                  <span className="font-semibold text-gray-700">Why this standard</span>
                  <p className="text-gray-600 mt-1">{result.reasoning}</p>
                </div>
              )}

              {result.allied_standards?.length > 0 && (
                <div>
                  <span className="font-semibold text-gray-700">Allied Standards</span>
                  <ul className="mt-1 space-y-1.5">
                    {result.allied_standards.map((s, idx) => (
                      <li key={idx} className="text-gray-600">
                        <span className="font-medium text-gray-800">{s.code}</span>
                        {s.in_corpus ? (
                          <span className="ml-2 text-[10px] uppercase tracking-wide bg-green-50 text-green-700 border border-green-200 px-1.5 py-0.5 rounded">
                            indexed
                          </span>
                        ) : (
                          <span
                            className="ml-2 text-[10px] uppercase tracking-wide bg-gray-100 text-gray-500 border border-gray-200 px-1.5 py-0.5 rounded"
                            title="Referenced by the primary standard, but this document is not in the local corpus"
                          >
                            not held
                          </span>
                        )}
                        {s.source === 'reference clause' && (
                          <span
                            className="ml-2 text-[10px] uppercase tracking-wide bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded"
                            title={
                              s.cited_on_page
                                ? 'Extracted from the references of the primary standard, page ' + s.cited_on_page
                                : 'Extracted from the references of the primary standard'
                            }
                          >
                            cited{s.cited_on_page ? ' p' + s.cited_on_page : ''}
                          </span>
                        )}
                        <span className="block text-gray-600">{s.role}</span>
                        {s.edition_note && (
                          <span className="block text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1 mt-1">
                            Edition mismatch: {s.edition_note}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <span className="font-semibold text-gray-700">Version Status</span>
                <p className="text-gray-600 mt-1">{result.version_status}</p>
              </div>

              <div>
                <span className="font-semibold text-gray-700">Certification Requirement</span>
                <p className="text-gray-600 mt-1">{result.certification}</p>
              </div>

              {/* Sources - the evidence the answer was built from. */}
              {result.sources?.length > 0 && (
                <div className="pt-4 border-t">
                  <span className="font-semibold text-gray-700">Sources</span>
                  <ul className="mt-1 space-y-1">
                    {result.sources.map((s, idx) => (
                      <li key={idx} className="text-gray-600 flex items-center gap-2">
                        <span>{s.citation.replace(' [OCR]', '')}</span>
                        {s.ocr && (
                          <span
                            className="text-[10px] uppercase tracking-wide bg-amber-50 text-amber-800 border border-amber-200 px-1.5 py-0.5 rounded"
                            title="This page was read from a scanned image using OCR"
                          >
                            OCR
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                  {usedOcr && (
                    <p className="mt-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
                      Pages marked OCR were read from scanned images. Character
                      recognition can misread symbols and digits, so check any
                      numerical limits or tolerances against the original document.
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Where to buy it on GeM */}
        {gem && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex justify-between items-start border-b pb-3 mb-4 gap-4">
              <div>
                <h3 className="font-bold text-gray-900 text-base">GeM Marketplace</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  Where this could be purchased on the Government e-Marketplace
                </p>
              </div>
              {gem.matched_on_standard ? (
                <span className="text-xs px-2.5 py-1 rounded border font-medium bg-green-50 text-green-800 border-green-200 whitespace-nowrap">
                  Matched on standard
                </span>
              ) : (
                <span className="text-xs px-2.5 py-1 rounded border font-medium bg-gray-50 text-gray-600 border-gray-200 whitespace-nowrap">
                  Matched on wording
                </span>
              )}
            </div>

            {gem.suggestions?.length > 0 ? (
              <ul className="space-y-2 text-sm">
                {gem.suggestions.map((s, idx) => (
                  <li key={idx} className="flex items-start justify-between gap-3 border-b last:border-0 pb-2 last:pb-0">
                    <div className="min-w-0">
                      <p className="font-medium text-gray-800">
                        {s.url ? (
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-red-900 hover:underline"
                          >
                            {s.product_name}
                          </a>
                        ) : (
                          s.product_name
                        )}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">{s.why}</p>
                      {s.primary_standard && (
                        <p className="text-xs text-gray-500">
                          Category cites {s.primary_standard}
                          {s.version ? ` (spec ${s.version})` : ''}
                        </p>
                      )}
                    </div>
                    <span
                      className={
                        'text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border whitespace-nowrap ' +
                        (s.match === 'standard'
                          ? 'bg-green-50 text-green-700 border-green-200'
                          : 'bg-gray-100 text-gray-500 border-gray-200')
                      }
                    >
                      {s.match === 'standard' ? 'cites standard' : 'keywords'}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-600">No GeM category matched.</p>
            )}

            {gem.note && (
              <p
                className={
                  'mt-3 text-xs rounded p-2 border ' +
                  (gem.weak
                    ? 'text-amber-800 bg-amber-50 border-amber-200'
                    : 'text-gray-600 bg-gray-50 border-gray-200')
                }
              >
                {gem.note}
              </p>
            )}
            {gem.caveat && (
              <p className="mt-2 text-xs text-gray-500">{gem.caveat}</p>
            )}
          </div>
        )}

        {/* Draft tender clauses */}
        {draft?.clauses?.length > 0 && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex justify-between items-start border-b pb-3 mb-4 gap-4">
              <div>
                <h3 className="font-bold text-gray-900 text-base">Draft Tender Clauses</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  A starting draft to edit - not tender-ready text
                </p>
              </div>
              <button
                onClick={copyDraft}
                className="text-xs border border-gray-300 hover:bg-gray-100 text-gray-700 px-3 py-1.5 rounded whitespace-nowrap"
              >
                {copied ? 'Copied' : 'Copy all'}
              </button>
            </div>

            <div className="space-y-4 text-sm">
              {draft.clauses.map((clause, idx) => (
                <div key={idx}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-gray-800">
                      {idx + 1}. {clause.heading}
                    </span>
                    {clause.grounded ? (
                      <span
                        className="text-[10px] uppercase tracking-wide bg-green-50 text-green-700 border border-green-200 px-1.5 py-0.5 rounded"
                        title={clause.basis || ''}
                      >
                        from the standard
                      </span>
                    ) : (
                      <span
                        className="text-[10px] uppercase tracking-wide bg-yellow-50 text-yellow-800 border border-yellow-300 px-1.5 py-0.5 rounded"
                        title={clause.basis || ''}
                      >
                        for you to complete
                      </span>
                    )}
                  </div>
                  <ClauseText text={clause.text} />
                  {clause.basis && (
                    <p className="text-[11px] text-gray-400 mt-1">{clause.basis}</p>
                  )}
                </div>
              ))}
            </div>

            {draft.placeholders?.length > 0 && (
              <p className="mt-4 pt-3 border-t text-xs text-gray-600">
                <span className="font-semibold">
                  {draft.placeholders.length} blank
                  {draft.placeholders.length === 1 ? '' : 's'} to fill:
                </span>{' '}
                {draft.placeholders.join(' · ')}
              </p>
            )}

            <p className="mt-3 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded p-3">
              {draft.caveat}
            </p>
          </div>
        )}
      </main>

      <footer className="max-w-4xl mx-auto px-4 pb-10 text-xs text-gray-500">
        PRISM is a decision-support prototype. Recommendations are not a
        determination of legal or contractual compliance, and certification
        requirements must be verified against current BIS listings.
      </footer>
    </div>
  );
}
