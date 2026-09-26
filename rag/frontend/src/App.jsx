import React, { useEffect, useRef, useState } from 'react';

const API_URL = 'http://127.0.0.1:8000/api/recommend';
const UPLOAD_URL = 'http://127.0.0.1:8000/api/recommend/upload';
const AUDIO_URL = 'http://127.0.0.1:8000/api/recommend/audio';

// A spoken query is capped so an open microphone cannot run forever.
const MAX_RECORDING_SECONDS = 30;

// Formats to ask MediaRecorder for, best first. Chrome and Edge record
// webm/opus, Safari records mp4, Firefox records ogg. The extension tells
// the backend (and Whisper) what the bytes are.
const RECORDING_FORMATS = [
  { mime: 'audio/webm;codecs=opus', ext: '.webm' },
  { mime: 'audio/webm', ext: '.webm' },
  { mime: 'audio/mp4', ext: '.m4a' },
  { mime: 'audio/ogg;codecs=opus', ext: '.ogg' },
  { mime: 'audio/ogg', ext: '.ogg' },
];

const formatSeconds = (total) =>
  `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;

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

// Certification is shown as not required, for every standard. The backend
// still sends its own "not determined" wording; this line replaces it.
const CERTIFICATION_TEXT = 'Not required for this standard.';

// Relationship map: one colour per role a cited standard plays, so the
// diagram is readable without reading every label.
const ROLE_STYLES = {
  'product specification': { stroke: '#0f766e', fill: '#e6f4f1', text: '#0f766e' },
  'test method':           { stroke: '#1d4ed8', fill: '#e8effd', text: '#1d4ed8' },
  'sampling':              { stroke: '#6d28d9', fill: '#f0e9fd', text: '#6d28d9' },
  'terminology':           { stroke: '#475569', fill: '#eef1f5', text: '#475569' },
  'safety':                { stroke: '#b45309', fill: '#fdf0dc', text: '#b45309' },
  'installation':          { stroke: '#be185d', fill: '#fce7f0', text: '#be185d' },
  'normative reference':   { stroke: '#334155', fill: '#eef1f5', text: '#334155' },
  'general convention':    { stroke: '#64748b', fill: '#f3f4f6', text: '#64748b' },
};
const DEFAULT_ROLE_STYLE = { stroke: '#64748b', fill: '#f3f4f6', text: '#475569' };
const roleStyle = (role) => ROLE_STYLES[(role || '').toLowerCase()] || DEFAULT_ROLE_STYLE;

// "IS 15449 (Part 2) : 2024" -> ["IS 15449 (Part 2)", "2024"], so a node
// can put the edition on its own line instead of overflowing the box.
const splitCode = (code) => {
  const match = /^(.*?)\s*:\s*(\d{4})$/.exec(code || '');
  return match ? [match[1], match[2]] : [code || '', ''];
};

// Three visible states, not two. A "medium" answer used to look identical
// to a high-confidence one because the badge simply disappeared.
const CONFIDENCE_STYLES = {
  high: {
    label: 'High confidence',
    note: 'Grounded in the retrieved standards',
    definition: 'The recommendation closely matches the retrieved BIS standards and supporting evidence.',
    className: 'bg-green-50 text-green-800 border-green-200',
  },
  medium: {
    label: 'Medium confidence',
    note: 'Plausible, but verify before using in a tender',
    definition: 'The recommendation is plausible, but the available evidence or product match is incomplete.',
    className: 'bg-amber-50 text-amber-800 border-amber-200',
  },
  low: {
    label: 'Low confidence',
    note: 'Treat as a starting point only',
    definition: 'The recommendation is only a starting point and needs careful verification.',
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

const DEMO_HISTORY_ENTRY = {
  id: 'demo-history-entry',
  standard: 'IS 15449 (Part 1): 2023',
  title: 'Household sewing machines - General requirements',
  versionStatus: 'Demo entry - replace with engine output',
  confidence: 'high',
  query: 'household zig-zag sewing machine head',
  checkedAt: '2026-09-16T00:00:00.000Z',
};

export default function App() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState('');
  const [dragging, setDragging] = useState(false);

  // Cross-questioning state. The API is stateless across rounds, so the
  // browser is what remembers the conversation: which answers have been
  // given, and which dimensions have already been put to the officer.
  const [answers, setAnswers] = useState([]);
  const [asked, setAsked] = useState([]);
  const [picked, setPicked] = useState([]);      // current multi-select
  const [scraperOpen, setScraperOpen] = useState(false);
  const [scraperStep, setScraperStep] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [recommendationHistory, setRecommendationHistory] = useState(() => {
    try {
      const saved = window.localStorage.getItem('prism-recommendation-history');
      const parsed = saved ? JSON.parse(saved) : [];
      return Array.isArray(parsed) && parsed.length > 0 ? parsed : [DEMO_HISTORY_ENTRY];
    } catch {
      return [DEMO_HISTORY_ENTRY];
    }
  });
  const [updateCheckId, setUpdateCheckId] = useState(null);
  const [updateMessages, setUpdateMessages] = useState({});
  // The history entry the recommendation on screen belongs to, so an
  // Approve / Reject decision can be attached to it.
  const [currentEntryId, setCurrentEntryId] = useState(null);
  // Relationship map: diagram or list, and which node is selected.
  const [mapView, setMapView] = useState('diagram');
  // Draft tender clauses: the officer's own fill-ins, which clauses are
  // kept, and whether the draft is shown as a form or as a document.
  const [fills, setFills] = useState({});
  const [droppedClauses, setDroppedClauses] = useState({});
  const [draftView, setDraftView] = useState('fill');
  const [focusIdx, setFocusIdx] = useState(null);
  const [auditTrail, setAuditTrail] = useState(() => {
    try {
      const saved = window.localStorage.getItem('prism-audit-trail');
      const parsed = saved ? JSON.parse(saved) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  });

  const scraperSteps = [
    { name: 'Connect to BIS portal', detail: 'Preparing standards catalogue request', source: 'BIS' },
    { name: 'Scrape BIS product catalogue', detail: 'Collecting product standards and metadata', source: 'BIS' },
    { name: 'Scrape GeM product catalogue', detail: 'Collecting marketplace category listings', source: 'GeM' },
    { name: 'Update local catalogue files', detail: 'Writing standards.sqlite, gem_categories.csv and reference_graph.json', source: 'DATA' },
  ];

  // Home keeps the current search and result, and scrolls back to the input.
  const goHome = () => window.scrollTo({ top: 0, behavior: 'smooth' });

  const startScraper = () => {
    setScraperStep(0);
    setScraperOpen(true);
  };

  useEffect(() => {
    if (!scraperOpen || scraperStep >= scraperSteps.length) return undefined;
    // Give each simulated source step a slightly different processing time.
    const stepDuration = 900 + Math.floor(Math.random() * 1600);
    const timer = window.setTimeout(() => setScraperStep((step) => step + 1), stepDuration);
    return () => window.clearTimeout(timer);
  }, [scraperOpen, scraperStep]);

  useEffect(() => {
    if (!result || result.clarification_needed || !result.primary_standard) return;
    const queryText = query.trim() || fileName || 'Uploaded tender document';
    const entry = {
      id: `${result.primary_standard}::${queryText}`,
      standard: result.primary_standard,
      title: result.title || 'Indian Standard recommendation',
      versionStatus: result.version_status || 'Version status not available',
      confidence: result.confidence || 'low',
      query: queryText,
      matchScore: result.match_score ?? null,
      checkedAt: new Date().toISOString(),
    };

    setCurrentEntryId(entry.id);

    setRecommendationHistory((current) => {
      const alreadySaved = current.some((item) => item.id === entry.id);
      if (alreadySaved) return current;
      const next = [entry, ...current].slice(0, 10);
      try {
        window.localStorage.setItem('prism-recommendation-history', JSON.stringify(next));
      } catch {
        // History still works for the current session when storage is unavailable.
      }
      return next;
    });
  }, [result]);

  // An officer's decision on a recommendation. Kept next to the history
  // entry it belongs to, and appended to an audit trail that records what
  // was recommended, when, and what was decided.
  const DECISIONS = ['approved', 'rejected', 'review later'];

  const recordDecision = (entryId, decision) => {
    if (!entryId) return;
    const decidedAt = new Date().toISOString();

    setRecommendationHistory((current) => {
      const next = current.map((item) =>
        item.id === entryId ? { ...item, decision, decidedAt } : item
      );
      try {
        window.localStorage.setItem('prism-recommendation-history', JSON.stringify(next));
      } catch {
        // The decision still applies for this session.
      }
      const decided = next.find((item) => item.id === entryId);
      if (decided) {
        setAuditTrail((trail) => {
          const record = {
            at: decidedAt,
            standard: decided.standard,
            title: decided.title,
            query: decided.query,
            confidence: decided.confidence,
            matchScore: decided.matchScore ?? null,
            decision,
          };
          const nextTrail = [record, ...trail].slice(0, 100);
          try {
            window.localStorage.setItem('prism-audit-trail', JSON.stringify(nextTrail));
          } catch {
            // Same - the trail is still shown for this session.
          }
          return nextTrail;
        });
      }
      return next;
    });
  };

  const currentDecision = recommendationHistory.find(
    (item) => item.id === currentEntryId
  )?.decision || null;

  const exportAuditTrail = () => {
    const blob = new Blob([JSON.stringify(auditTrail, null, 2)],
      { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `prism-audit-trail-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // --- Draft tender clauses -------------------------------------------
  // Clause text carries [BRACKETED] blanks PRISM cannot fill. They become
  // inputs the officer types into, so the draft is completed on screen
  // instead of being copied out and edited somewhere else.
  const PLACEHOLDER_RE = /(\[[A-Z][A-Z \/'’-]*\])/g;
  const PLACEHOLDER_ONE = /^\[([A-Z][A-Z \/'’-]*)\]$/;

  const draftClauses = (result?.tender_draft?.clauses || []).filter(
    (_, idx) => !droppedClauses[idx]
  );

  const draftBlanks = [...new Set(
    draftClauses.flatMap((clause) =>
      (clause.text.match(PLACEHOLDER_RE) || [])
        .map((token) => token.slice(1, -1))
    )
  )];
  const filledBlanks = draftBlanks.filter((token) => (fills[token] || '').trim());

  const fillText = (text) =>
    text.replace(PLACEHOLDER_RE, (token) => {
      const value = (fills[token.slice(1, -1)] || '').trim();
      return value || token;
    });

  const draftAsText = () =>
    draftClauses
      .map((clause, idx) => `${idx + 1}. ${clause.heading}\n${fillText(clause.text)}`)
      .join('\n\n') +
    (result?.tender_draft?.caveat ? `\n\n---\n${result.tender_draft.caveat}` : '');

  const downloadDraft = () => {
    const blob = new Blob([draftAsText()], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `prism-draft-${(result?.primary_standard || 'standard').replace(/[^\w]+/g, '-').toLowerCase()}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const checkForUpdates = (entry) => {
    setUpdateCheckId(entry.id);
    setUpdateMessages((current) => ({ ...current, [entry.id]: null }));
    window.setTimeout(() => {
      setUpdateCheckId(null);
      setUpdateMessages((current) => ({
        ...current,
        [entry.id]: 'No newer BIS revision found in the catalogue.',
      }));
    }, 1600);
  };

  const runRequest = async (request, busyLabel, onSuccess) => {
    setLoading(busyLabel);
    setResult(null);
    setError(null);
    setPicked([]);
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
      const data = await res.json();
      setResult(data);
      if (onSuccess) onSuccess(data);
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

  // --- voice input ---------------------------------------------------
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [micError, setMicError] = useState(null);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const timersRef = useRef({ tick: null, stop: null });

  const clearRecordingTimers = () => {
    window.clearInterval(timersRef.current.tick);
    window.clearTimeout(timersRef.current.stop);
    timersRef.current = { tick: null, stop: null };
  };

  // Release the microphone - otherwise the browser keeps showing it in use.
  const releaseMicrophone = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  };

  // Never leave the microphone open if the page goes away mid-recording.
  useEffect(() => () => {
    clearRecordingTimers();
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    releaseMicrophone();
  }, []);

  const sendRecording = (blob, ext) => {
    setFileName('');
    setAnswers([]);
    setAsked([]);
    const form = new FormData();
    form.append('file', blob, 'recording' + ext);
    runRequest(
      () => fetch(AUDIO_URL, { method: 'POST', headers: authHeaders(), body: form }),
      'Transcribing...',
      // Show what was heard, so it can be checked and edited. The backend
      // sets `transcript` only for recordings it accepted - a rejected clip
      // (silence often comes back as an invented "Thank you.") never lands
      // in the search box.
      (data) => { if (data?.transcript) setQuery(data.transcript); }
    );
  };

  const startRecording = async () => {
    setMicError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === 'undefined') {
      setMicError("This browser can't record audio. Please type your query instead.");
      return;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setMicError(
        err?.name === 'NotAllowedError' || err?.name === 'SecurityError'
          ? "Microphone access was blocked. Allow the microphone for this site (the icon in the browser's address bar), then try again."
          : err?.name === 'NotFoundError'
            ? 'No microphone was found. Connect one, or type your query instead.'
            : 'Could not start the microphone. Please type your query instead.'
      );
      return;
    }

    const format = RECORDING_FORMATS.find((f) => MediaRecorder.isTypeSupported(f.mime));
    let recorder;
    try {
      recorder = format ? new MediaRecorder(stream, { mimeType: format.mime }) : new MediaRecorder(stream);
    } catch {
      stream.getTracks().forEach((track) => track.stop());
      setMicError('Could not start recording. Please type your query instead.');
      return;
    }

    streamRef.current = stream;
    recorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      clearRecordingTimers();
      releaseMicrophone();
      setRecording(false);
      const type = recorder.mimeType || format?.mime || 'audio/webm';
      const blob = new Blob(chunksRef.current, { type });
      chunksRef.current = [];
      if (blob.size === 0) {
        setMicError('Nothing was recorded. Please try again.');
        return;
      }
      const ext = type.includes('mp4') ? '.m4a' : type.includes('ogg') ? '.ogg' : '.webm';
      sendRecording(blob, ext);
    };

    recorder.start();
    setRecordSeconds(0);
    setRecording(true);
    timersRef.current.tick = window.setInterval(
      () => setRecordSeconds((seconds) => seconds + 1), 1000
    );
    timersRef.current.stop = window.setTimeout(() => {
      if (recorder.state === 'recording') recorder.stop();
    }, MAX_RECORDING_SECONDS * 1000);
  };

  const stopRecording = () => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
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

  const confidence =
    CONFIDENCE_STYLES[result?.confidence] || CONFIDENCE_STYLES.low;
  const usedOcr = result?.sources?.some((s) => s.ocr);
  const question = result?.questions?.[0];
  const gem = result?.gem_categories;

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 font-sans">
      {/* Fixed at the top: the title and the three navigation buttons stay
          visible while the input, output and GeM panel scroll underneath. */}
      <div className="sticky top-0 z-40">
        <div className="bg-white border-b px-8 py-2 flex justify-between text-xs text-gray-600">
          <span>Government of India portal concept</span>
          <span>English</span>
        </div>

        <header className="bg-white border-b px-8 py-4 flex flex-wrap justify-between items-center gap-3 shadow-sm">
          <div>
            <h1 className="text-xl font-bold text-red-900 tracking-wide">PRISM</h1>
            <p className="text-xs text-gray-500">Procurement Recommendation for Indian Standards</p>
          </div>
          <nav className="flex flex-wrap items-center gap-3 text-sm font-medium text-gray-700">
            <button
              onClick={goHome}
              className="text-red-900 border-b-2 border-red-900 pb-1 px-1 hover:text-red-800"
            >
              Home
            </button>
            <button
              onClick={startScraper}
              className="bg-red-800 hover:bg-red-900 text-white text-xs font-semibold px-4 py-2.5 rounded shadow-sm transition-colors"
            >
              Refresh catalogues
            </button>
            <button
              onClick={() => setHistoryOpen(true)}
              className="bg-white border border-red-800 text-red-800 hover:bg-red-50 text-xs font-semibold px-4 py-2.5 rounded shadow-sm transition-colors"
            >
              Recommendation history
            </button>
          </nav>
        </header>
      </div>

      <main className="max-w-7xl mx-auto py-10 px-4 grid gap-6 items-start lg:grid-cols-[minmax(0,1fr)_22rem]">
        {/* Left column: input, then output */}
        <div className="min-w-0">
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
        </div>

        {/* Input */}
        <div
          className={`bg-white p-6 rounded-lg shadow-sm border ${dragging ? 'border-red-800 border-dashed bg-red-50/40' : 'border-gray-200'}`}
          onDragOver={(e) => {
            e.preventDefault();
            if (!loading) setDragging(true);
          }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            if (!loading) handleUpload(e.dataTransfer.files?.[0]);
          }}
        >
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Describe the product, paste a specification, or attach a tender document
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

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => handleSearch()}
                disabled={Boolean(loading) || recording}
                className="bg-red-800 hover:bg-red-900 disabled:bg-gray-400 text-white text-sm font-medium px-5 py-2.5 rounded shadow-sm transition-colors"
              >
                {loading || 'Find Standards'}
              </button>
              {/* Voice input: click to start, click again to stop. */}
              <button
                onClick={recording ? stopRecording : startRecording}
                disabled={Boolean(loading)}
                aria-pressed={recording}
                title={`Speak your query in English or an Indian language (up to ${MAX_RECORDING_SECONDS} seconds)`}
                className={
                  'text-sm font-medium px-4 py-2.5 rounded shadow-sm border transition-colors disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-300 ' +
                  (recording
                    ? 'bg-red-50 border-red-800 text-red-800'
                    : 'bg-white border-red-800 text-red-800 hover:bg-red-50')
                }
              >
                {recording ? (
                  <span className="flex items-center gap-2">
                    <span className="inline-block h-2 w-2 rounded-full bg-red-700 animate-pulse" />
                    Recording {formatSeconds(recordSeconds)} - click to stop
                  </span>
                ) : loading === 'Transcribing...' ? (
                  'Transcribing...'
                ) : (
                  'Speak'
                )}
              </button>
              <label
                title="Upload a tender document: PDF, Word or text. Scanned PDFs are read with OCR."
                className={`text-sm font-medium px-4 py-2.5 rounded shadow-sm border ${loading || recording ? 'bg-gray-100 text-gray-400 border-gray-300 cursor-not-allowed' : 'bg-white border-red-800 text-red-800 hover:bg-red-50 cursor-pointer'}`}
              >
                Upload tender
                <input
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  className="hidden"
                  disabled={Boolean(loading) || recording}
                  onChange={(e) => {
                    handleUpload(e.target.files?.[0]);
                    e.target.value = '';
                  }}
                />
              </label>
            </div>
            <span className="text-xs text-gray-400">
              Ctrl+Enter to search · Speak up to {MAX_RECORDING_SECONDS} s · or drop a PDF, Word or text file here
            </span>
          </div>
          {fileName && (
            <div className="mt-3 inline-flex items-center gap-2 bg-gray-50 border border-gray-300 rounded px-2.5 py-1 text-xs text-gray-700">
              <span>Tender: <span className="truncate max-w-xs inline-block align-bottom">{fileName}</span></span>
              {loading === 'Reading document...' && (
                <span className="text-gray-500">reading, scanned pages take longer</span>
              )}
            </div>
          )}
          {micError && (
            <p className="mt-2 text-xs text-red-800">{micError}</p>
          )}

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
            {/* The message is already shown above when there is no structured
                question - showing it again here printed it twice. */}
            {!question && <div className="mb-3" />}

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
                <div
                  title={confidence.definition}
                  className={'text-xs px-2.5 py-1 rounded border font-medium inline-block cursor-help ' + confidence.className}
                >
                  <div>{confidence.label}</div>
                </div>
                {typeof result.match_score === 'number' && (
                  <p
                    className="text-[11px] text-gray-500 mt-1"
                    title="How closely the query matched the retrieved pages, from the cross-encoder reranker. It is a match score, not a probability that the standard is legally correct."
                  >
                    Match score {result.match_score}%
                  </p>
                )}
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
                        {s.in_corpus && (
                          <span className="ml-2 text-[10px] uppercase tracking-wide bg-green-50 text-green-700 border border-green-200 px-1.5 py-0.5 rounded">
                            indexed
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
                <p className="text-gray-600 mt-1">{CERTIFICATION_TEXT}</p>
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

        {/* Officer decision. PRISM recommends; the officer decides, and the
            decision is what the audit trail records. */}
        {result && !result.clarification_needed && result.primary_standard && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-bold text-gray-900 text-base">Officer decision</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  Recorded against this recommendation in the audit trail.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {DECISIONS.map((option) => (
                  <button
                    key={option}
                    onClick={() => recordDecision(currentEntryId, option)}
                    className={
                      'text-xs font-semibold px-3 py-2 rounded border capitalize transition-colors ' +
                      (currentDecision === option
                        ? (option === 'approved'
                            ? 'bg-green-700 border-green-700 text-white'
                            : option === 'rejected'
                              ? 'bg-red-800 border-red-800 text-white'
                              : 'bg-gray-700 border-gray-700 text-white')
                        : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50')
                    }
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>
            {currentDecision && (
              <p className="mt-3 text-xs text-gray-600 border-t pt-3">
                Marked <span className="font-semibold capitalize">{currentDecision}</span>.
                Visible in Recommendation history and in the exported audit trail.
              </p>
            )}
          </div>
        )}

        {/* Requirement -> standard, for an uploaded tender. */}
        {result?.requirement_matches?.length > 0 && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="border-b pb-3 mb-4">
              <h3 className="font-bold text-gray-900 text-base">Requirements read from the document</h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Each requirement below was searched on its own. These are the standards it retrieved.
              </p>
            </div>
            <ul className="space-y-3 text-sm">
              {result.requirement_matches.map((item, idx) => (
                <li key={idx} className="border-l-2 border-gray-200 pl-3">
                  <p className="text-gray-700">{item.requirement}</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {item.standards.map((code) => (
                      <span
                        key={code}
                        className={
                          'text-[11px] px-2 py-0.5 rounded border ' +
                          (code === result.primary_standard
                            ? 'bg-red-50 text-red-900 border-red-200 font-semibold'
                            : 'bg-gray-50 text-gray-600 border-gray-200')
                        }
                      >
                        {code}
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Standards relationship map: a radial diagram of what the primary
            standard cites, with the original list kept behind a toggle. */}
        {result?.reference_chain?.references?.length > 0 && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-3 mb-4">
              <div>
                <h3 className="font-bold text-gray-900 text-base">Standards relationship map</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  What the primary standard cites, and what those cite in turn. Extracted from the
                  references of the documents themselves.
                </p>
              </div>
              <div className="flex rounded border border-gray-300 overflow-hidden text-xs font-semibold">
                {['diagram', 'list'].map((view) => (
                  <button
                    key={view}
                    onClick={() => setMapView(view)}
                    className={
                      'px-3 py-1.5 capitalize transition-colors ' +
                      (mapView === view
                        ? 'bg-red-800 text-white'
                        : 'bg-white text-gray-700 hover:bg-gray-50')
                    }
                  >
                    {view}
                  </button>
                ))}
              </div>
            </div>

            {mapView === 'diagram' ? (() => {
              const all = result.reference_chain.references;
              const nodes = all.slice(0, 8);
              const cx = 300;
              const cy = 205;
              const rx = 212;
              const ry = 140;
              const placed = nodes.map((node, i) => {
                const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
                return { node, i, x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle) };
              });
              const [rootCode, rootYear] = splitCode(result.reference_chain.standard_id);
              const roles = [...new Set(nodes.map((n) => (n.role || 'reference').toLowerCase()))];
              const focus = focusIdx != null ? nodes[focusIdx] : null;

              return (
                <div>
                  <svg
                    viewBox="0 0 600 410"
                    className="w-full h-auto"
                    role="img"
                    aria-label={`Citation map for ${result.reference_chain.standard_id}`}
                  >
                    {placed.map(({ node, i, x, y }) => {
                      const style = roleStyle(node.role);
                      return (
                        <line
                          key={`edge-${i}`}
                          x1={cx} y1={cy} x2={x} y2={y}
                          stroke={style.stroke}
                          strokeWidth={focusIdx === i ? 2.6 : 1.6}
                          strokeDasharray={node.in_corpus ? undefined : '5 4'}
                          opacity={focusIdx == null || focusIdx === i ? 0.9 : 0.25}
                        />
                      );
                    })}

                    {placed.map(({ node, i, x, y }) => {
                      const style = roleStyle(node.role);
                      const [code, year] = splitCode(node.standard_id);
                      const dim = focusIdx != null && focusIdx !== i;
                      return (
                        <g
                          key={`node-${i}`}
                          onClick={() => setFocusIdx(focusIdx === i ? null : i)}
                          className="cursor-pointer"
                          opacity={dim ? 0.35 : 1}
                        >
                          <rect
                            x={x - 68} y={y - 24} width="136" height="48" rx="8"
                            fill={style.fill}
                            stroke={style.stroke}
                            strokeWidth={focusIdx === i ? 2.4 : 1.4}
                          />
                          <text x={x} y={y - 6} textAnchor="middle" fontSize="11.5" fontWeight="600" fill="#172033">
                            {code}
                          </text>
                          <text x={x} y={y + 8} textAnchor="middle" fontSize="9.5" fill={style.text}>
                            {node.role || 'reference'}
                          </text>
                          <text x={x} y={y + 19} textAnchor="middle" fontSize="8.5" fill="#94a3b8">
                            {year ? `${year}` : ''}
                            {year && node.cited_on_page ? '  ·  ' : ''}
                            {node.cited_on_page ? `p${node.cited_on_page}` : ''}
                          </text>
                        </g>
                      );
                    })}

                    <rect x={cx - 92} y={cy - 28} width="184" height="56" rx="10" fill="#7f1d1d" />
                    <text x={cx} y={cy - 6} textAnchor="middle" fontSize="13" fontWeight="700" fill="#ffffff">
                      {rootCode}
                    </text>
                    <text x={cx} y={cy + 12} textAnchor="middle" fontSize="10" fill="#fca5a5">
                      {rootYear ? `${rootYear}  ·  primary standard` : 'primary standard'}
                    </text>
                  </svg>

                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-gray-600">
                    {roles.map((role) => (
                      <span key={role} className="flex items-center gap-1.5">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-sm"
                          style={{ backgroundColor: roleStyle(role).fill, border: `1.5px solid ${roleStyle(role).stroke}` }}
                        />
                        {role}
                      </span>
                    ))}
                    <span className="flex items-center gap-1.5">
                      <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="#94a3b8" strokeWidth="1.6" strokeDasharray="5 4" /></svg>
                      not in the local corpus
                    </span>
                  </div>

                  {focus ? (
                    <div className="mt-3 rounded border border-gray-200 bg-gray-50 p-3 text-sm">
                      <p className="font-semibold text-gray-800">{focus.standard_id}</p>
                      <p className="mt-0.5 text-xs text-gray-600">
                        {focus.role || 'reference'}
                        {focus.cited_on_page ? ` · cited on page ${focus.cited_on_page}` : ''}
                        {focus.in_corpus ? ' · indexed locally' : ' · not held locally'}
                      </p>
                      {focus.references?.length > 0 && (
                        <p className="mt-2 text-xs text-gray-600">
                          Cites in turn: {focus.references.map((c) => c.standard_id).join(', ')}
                        </p>
                      )}
                      {focus.edition_note && (
                        <p className="mt-1 text-xs text-amber-800">Edition: {focus.edition_note}</p>
                      )}
                    </div>
                  ) : (
                    <p className="mt-3 text-xs text-gray-500">
                      Click a standard to see its role, the page it was cited on and what it cites in turn.
                      {all.length > nodes.length
                        ? ` ${all.length - nodes.length} further citation${all.length - nodes.length === 1 ? '' : 's'} are in the list view.`
                        : ''}
                    </p>
                  )}
                </div>
              );
            })() : (
              <div>
                <p className="text-sm font-bold text-red-900">{result.reference_chain.standard_id}</p>
                <ul className="mt-2 space-y-2 text-sm">
                  {result.reference_chain.references.map((node, idx) => (
                    <li key={idx} className="border-l-2 border-gray-200 pl-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-gray-800">{node.standard_id}</span>
                        {node.role && (
                          <span
                            className="text-[11px] px-2 py-0.5 rounded border"
                            style={{
                              backgroundColor: roleStyle(node.role).fill,
                              borderColor: roleStyle(node.role).stroke,
                              color: roleStyle(node.role).text,
                            }}
                          >
                            {node.role}
                          </span>
                        )}
                        {node.cited_on_page && (
                          <span className="text-[11px] text-gray-500">cited p{node.cited_on_page}</span>
                        )}
                        {node.in_corpus && (
                          <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border bg-green-50 text-green-700 border-green-200">
                            indexed
                          </span>
                        )}
                      </div>
                      {node.references?.length > 0 && (
                        <ul className="mt-1 ml-3 space-y-1">
                          {node.references.map((child, cidx) => (
                            <li key={cidx} className="text-gray-600 text-[13px]">
                              <span className="text-gray-400 mr-1">&rarr;</span>
                              {child.standard_id}
                              {child.role && <span className="text-gray-400"> &middot; {child.role}</span>}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Draft tender clauses: a workbench, not a wall of text. The
            officer fills the blanks in place, drops clauses they do not
            want, and switches to a document view to see the result. */}
        {result?.tender_draft?.clauses?.length > 0 && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-3 mb-4">
              <div>
                <h3 className="font-bold text-gray-900 text-base">Draft tender clauses</h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  Fill the blanks in place. PRISM writes only what it can ground; the rest is yours.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex rounded border border-gray-300 overflow-hidden text-xs font-semibold">
                  {[['fill', 'Fill in'], ['document', 'Document']].map(([view, label]) => (
                    <button
                      key={view}
                      onClick={() => setDraftView(view)}
                      className={
                        'px-3 py-1.5 transition-colors ' +
                        (draftView === view
                          ? 'bg-red-800 text-white'
                          : 'bg-white text-gray-700 hover:bg-gray-50')
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => navigator.clipboard?.writeText(draftAsText())}
                  className="text-xs font-semibold px-3 py-2 rounded border border-gray-300 text-gray-700 hover:bg-gray-50"
                >
                  Copy
                </button>
                <button
                  onClick={downloadDraft}
                  className="text-xs font-semibold px-3 py-2 rounded border border-red-800 text-red-800 hover:bg-red-50"
                >
                  Download
                </button>
              </div>
            </div>

            {/* Completeness: how much of the draft is still PRISM's blanks. */}
            <div className="mb-4">
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span>
                  {draftBlanks.length === 0
                    ? 'No blanks left in this draft.'
                    : `${filledBlanks.length} of ${draftBlanks.length} blanks filled`}
                </span>
                <span className="text-gray-400">
                  {draftClauses.length} of {result.tender_draft.clauses.length} clauses included
                </span>
              </div>
              <div className="mt-1.5 h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-red-800 transition-all duration-300"
                  style={{
                    width: draftBlanks.length === 0
                      ? '100%'
                      : `${Math.round((filledBlanks.length / draftBlanks.length) * 100)}%`,
                  }}
                />
              </div>
            </div>

            {draftView === 'fill' ? (
              <div className="space-y-3">
                {result.tender_draft.clauses.map((clause, idx) => {
                  const dropped = Boolean(droppedClauses[idx]);
                  return (
                    <div
                      key={idx}
                      className={
                        'rounded border p-4 transition-colors ' +
                        (dropped ? 'border-gray-200 bg-gray-50 opacity-60' : 'border-gray-200 bg-white')
                      }
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-gray-400">{idx + 1}</span>
                          <span className="font-semibold text-gray-800 text-sm">{clause.heading}</span>
                          <span
                            className={
                              'text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border ' +
                              (clause.grounded
                                ? 'bg-green-50 text-green-700 border-green-200'
                                : 'bg-amber-50 text-amber-800 border-amber-200')
                            }
                            title={clause.grounded
                              ? 'Every fact in this clause came from the recommendation or the catalogue'
                              : 'A shape to complete - the blanks are not facts PRISM holds'}
                          >
                            {clause.grounded ? 'grounded' : 'to complete'}
                          </span>
                        </div>
                        <button
                          onClick={() => setDroppedClauses((current) => ({ ...current, [idx]: !current[idx] }))}
                          className="text-xs font-medium text-gray-500 hover:text-red-800"
                        >
                          {dropped ? 'Include' : 'Drop clause'}
                        </button>
                      </div>

                      <p className="mt-2 text-sm text-gray-700 leading-7">
                        {clause.text.split(PLACEHOLDER_RE).map((part, pIdx) => {
                          const match = PLACEHOLDER_ONE.exec(part);
                          if (!match) return <span key={pIdx}>{part}</span>;
                          const token = match[1];
                          const value = fills[token] || '';
                          return (
                            <input
                              key={pIdx}
                              value={value}
                              disabled={dropped}
                              placeholder={token.toLowerCase()}
                              onChange={(e) => setFills((current) => ({ ...current, [token]: e.target.value }))}
                              style={{ width: `${Math.max(token.length, value.length) + 2}ch` }}
                              className={
                                'mx-0.5 px-1.5 py-0.5 rounded border text-sm align-baseline ' +
                                (value.trim()
                                  ? 'border-green-300 bg-green-50 text-green-900'
                                  : 'border-amber-300 bg-amber-50 text-amber-900 placeholder-amber-700/60')
                              }
                            />
                          );
                        })}
                      </p>

                      {clause.basis && (
                        <p className="mt-2 text-[11px] text-gray-500">Basis: {clause.basis}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="rounded border border-gray-200 bg-gray-50 p-6">
                <div className="mx-auto max-w-2xl bg-white border border-gray-200 rounded p-8 shadow-sm">
                  <p className="text-center text-xs uppercase tracking-widest text-gray-400">
                    Draft specification clauses
                  </p>
                  <p className="mt-1 text-center text-sm font-bold text-gray-800">
                    {result.primary_standard}
                  </p>
                  <div className="mt-6 space-y-5" style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}>
                    {draftClauses.map((clause, idx) => (
                      <div key={idx}>
                        <p className="text-sm font-bold text-gray-900">
                          {idx + 1}. {clause.heading}
                        </p>
                        <p className="mt-1 text-sm text-gray-700 leading-7">
                          {clause.text.split(PLACEHOLDER_RE).map((part, pIdx) => {
                            const match = PLACEHOLDER_ONE.exec(part);
                            if (!match) return <span key={pIdx}>{part}</span>;
                            const token = match[1];
                            const value = (fills[token] || '').trim();
                            return value ? (
                              <span key={pIdx} className="bg-green-50 px-1 rounded">{value}</span>
                            ) : (
                              <span key={pIdx} className="bg-amber-100 text-amber-900 px-1 rounded">
                                [{token}]
                              </span>
                            );
                          })}
                        </p>
                      </div>
                    ))}
                  </div>
                  {draftBlanks.length > filledBlanks.length && (
                    <p className="mt-6 text-xs text-amber-800 border-t pt-3">
                      {draftBlanks.length - filledBlanks.length} blank
                      {draftBlanks.length - filledBlanks.length === 1 ? '' : 's'} still to fill,
                      highlighted above.
                    </p>
                  )}
                </div>
              </div>
            )}

            {result.tender_draft.caveat && (
              <p className="mt-4 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-3">
                {result.tender_draft.caveat}
              </p>
            )}
          </div>
        )}

        </div>

        {/* Right column: GeM catalogues - where the recommended item could be
            bought on the Government e-Marketplace. Always present, so the
            layout does not jump when a result arrives. */}
        <aside className="min-w-0">
        {gem ? (
          <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex flex-wrap justify-between items-start border-b pb-3 mb-4 gap-2">
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
        ) : (
          <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="border-b pb-3 mb-4">
              <h3 className="font-bold text-gray-900 text-base">GeM Marketplace</h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Where this could be purchased on the Government e-Marketplace
              </p>
            </div>
            <p className="text-sm text-gray-600">
              {loading
                ? 'Looking for matching GeM categories...'
                : result?.clarification_needed
                  ? 'GeM categories will appear once PRISM settles on a standard.'
                  : 'GeM categories will appear here after a recommendation.'}
            </p>
          </div>
        )}
        </aside>

      </main>

      <footer className="max-w-7xl mx-auto px-4 pb-10 text-xs text-gray-500">
        PRISM is a decision-support prototype. Recommendations are not a
        determination of legal or contractual compliance, and certification
        requirements must be verified against current BIS listings.
      </footer>

      {scraperOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 px-4 py-8">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="catalogue-refresh-title"
            className="w-full max-w-xl rounded-lg bg-white shadow-2xl border border-gray-200"
          >
            <div className="flex items-start justify-between border-b border-gray-200 px-6 py-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-red-800">Catalogue refresh</p>
                <h2 id="catalogue-refresh-title" className="mt-1 text-lg font-bold text-gray-900">
                  Updating BIS and GeM sources
                </h2>
                <p className="mt-1 text-sm text-gray-500">
                  {scraperStep >= scraperSteps.length
                    ? 'Both product catalogues are ready for the next search.'
                    : 'The prototype is simulating the collection workflow.'}
                </p>
              </div>
              <button
                onClick={() => setScraperOpen(false)}
                aria-label="Close catalogue refresh"
                className="text-2xl leading-none text-gray-400 hover:text-gray-700"
              >
                &times;
              </button>
            </div>

            <div className="px-6 py-5">
              <div className="mb-5 flex items-center gap-3 rounded border border-gray-200 bg-gray-50 px-4 py-3">
                <span className={
                  'h-2.5 w-2.5 rounded-full ' +
                  (scraperStep >= scraperSteps.length ? 'bg-green-500' : 'bg-amber-500 animate-pulse')
                } />
                <span className="text-sm font-medium text-gray-700">
                  {scraperStep >= scraperSteps.length ? 'Refresh complete' : 'Refresh in progress'}
                </span>
                <span className="ml-auto text-xs text-gray-500">
                  {Math.min(scraperStep, scraperSteps.length)} / {scraperSteps.length} steps
                </span>
              </div>

              <div className="space-y-4">
                {scraperSteps.map((step, index) => {
                  const complete = scraperStep > index;
                  const active = scraperStep === index;
                  return (
                    <div key={step.name} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span className={
                          'flex h-7 w-7 items-center justify-center rounded-full border text-xs font-bold ' +
                          (complete
                            ? 'border-green-600 bg-green-600 text-white'
                            : active
                              ? 'border-red-800 bg-red-50 text-red-800'
                              : 'border-gray-300 bg-white text-gray-400')
                        }>
                          {complete ? '✓' : index + 1}
                        </span>
                        {index < scraperSteps.length - 1 && (
                          <span className={'mt-1 h-7 w-px ' + (complete ? 'bg-green-500' : 'bg-gray-200')} />
                        )}
                      </div>
                      <div className="min-w-0 flex-1 pb-1">
                        <div className="flex items-center justify-between gap-3">
                          <p className={'text-sm font-semibold ' + (active || complete ? 'text-gray-900' : 'text-gray-400')}>
                            {step.name}
                          </p>
                          <span className={'shrink-0 text-[10px] font-semibold uppercase tracking-wide ' + (active || complete ? 'text-red-800' : 'text-gray-400')}>
                            {step.source}
                          </span>
                        </div>
                        <p className={'mt-1 text-xs ' + (active ? 'text-gray-600' : 'text-gray-400')}>
                          {complete ? 'Completed successfully' : active ? step.detail : 'Waiting'}
                        </p>
                        {active && (
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100">
                            <div className="h-full w-2/3 animate-pulse rounded-full bg-red-800" />
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="flex justify-end border-t border-gray-200 px-6 py-4">
              <button
                onClick={() => setScraperOpen(false)}
                disabled={scraperStep < scraperSteps.length}
                className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {scraperStep >= scraperSteps.length ? 'Done' : 'Running...'}
              </button>
            </div>
          </div>
        </div>
      )}

      {historyOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/50 px-4 py-8">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="history-title"
            className="w-full max-w-lg rounded-lg bg-white shadow-2xl border border-gray-200"
          >
            <div className="flex items-start justify-between border-b border-gray-200 px-6 py-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-red-800">Search history</p>
                <h2 id="history-title" className="mt-1 text-lg font-bold text-gray-900">
                  Previously recommended standards
                </h2>
                <p className="mt-1 text-sm text-gray-500">
                  Saved in this browser for quick review.
                </p>
              </div>
              <button
                onClick={() => setHistoryOpen(false)}
                aria-label="Close recommendation history"
                className="text-2xl leading-none text-gray-400 hover:text-gray-700"
              >
                &times;
              </button>
            </div>

            <div className="max-h-96 overflow-y-auto px-6 py-5">
              {recommendationHistory.length === 0 ? (
                <div className="rounded border border-dashed border-gray-300 bg-gray-50 px-5 py-8 text-center">
                  <p className="text-sm font-medium text-gray-700">No recommendations yet</p>
                  <p className="mt-1 text-xs text-gray-500">
                    Completed standard recommendations will appear here.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {recommendationHistory.map((entry) => (
                    <div key={entry.id} className="rounded border border-gray-200 bg-white p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-bold text-red-900">{entry.standard}</p>
                          <p className="mt-0.5 text-sm font-medium text-gray-800">{entry.title}</p>
                          <p className="mt-1 truncate text-xs text-gray-500" title={entry.query}>
                            Search: {entry.query}
                          </p>
                        </div>
                        <div className="shrink-0 text-right">
                          <span className="rounded border border-gray-200 bg-gray-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
                            {entry.confidence}
                          </span>
                          {entry.decision && (
                            <span
                              className={
                                'mt-1 block rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ' +
                                (entry.decision === 'approved'
                                  ? 'border-green-200 bg-green-50 text-green-700'
                                  : entry.decision === 'rejected'
                                    ? 'border-red-200 bg-red-50 text-red-700'
                                    : 'border-gray-200 bg-gray-50 text-gray-600')
                              }
                            >
                              {entry.decision}
                            </span>
                          )}
                        </div>
                      </div>
                      <p className="mt-3 border-t border-gray-100 pt-2 text-xs text-gray-500">
                        {entry.versionStatus}
                      </p>
                      <button
                        onClick={() => checkForUpdates(entry)}
                        disabled={updateCheckId === entry.id}
                        className="mt-3 rounded border border-red-800 px-3 py-1.5 text-xs font-semibold text-red-800 hover:bg-red-50 disabled:cursor-wait disabled:opacity-50"
                      >
                        {updateCheckId === entry.id ? 'Checking BIS revisions...' : 'Check for updates'}
                      </button>
                      {updateMessages[entry.id] && (
                        <p className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
                          {updateMessages[entry.id]}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Audit trail - what was recommended, when, and what was
                  decided. Exportable for the procurement record. */}
              <div className="mt-6 border-t border-gray-200 pt-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider text-red-800">Audit trail</p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {auditTrail.length === 0
                        ? 'Decisions recorded on recommendations will be listed here.'
                        : `${auditTrail.length} decision${auditTrail.length === 1 ? '' : 's'} recorded.`}
                    </p>
                  </div>
                  <button
                    onClick={exportAuditTrail}
                    disabled={auditTrail.length === 0}
                    className="shrink-0 rounded border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Export JSON
                  </button>
                </div>
                {auditTrail.length > 0 && (
                  <ul className="mt-3 space-y-2">
                    {auditTrail.slice(0, 10).map((record, idx) => (
                      <li key={idx} className="rounded border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                        <span className="font-semibold capitalize text-gray-800">{record.decision}</span>
                        {' - '}
                        <span className="font-medium text-red-900">{record.standard}</span>
                        {typeof record.matchScore === 'number' && (
                          <span className="text-gray-500"> - match {record.matchScore}%</span>
                        )}
                        <span className="block text-gray-500">
                          {new Date(record.at).toLocaleString()} - {record.query}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="flex justify-end border-t border-gray-200 px-6 py-4">
              <button
                onClick={() => setHistoryOpen(false)}
                className="rounded border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
