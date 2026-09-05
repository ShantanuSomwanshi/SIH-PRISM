import React, { useState } from 'react';

const API_URL = 'http://127.0.0.1:8000/api/recommend';

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

export default function App() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async (textToSearch) => {
    const searchText = (textToSearch || query || '').trim();
    if (!searchText) return;

    setLoading(true);
    setResult(null);
    setError(null);

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchText }),
      });

      if (!res.ok) {
        // Surface the server's own message where there is one.
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
      // "Failed to fetch" means the request never reached the server:
      // backend not running, or blocked by CORS.
      setError(
        err.message === 'Failed to fetch'
          ? 'Could not reach the PRISM API at 127.0.0.1:8000. Check that the backend is running (uvicorn backend.main:app --reload).'
          : err.message
      );
    } finally {
      setLoading(false);
    }
  };

  const confidence =
    CONFIDENCE_STYLES[result?.confidence] || CONFIDENCE_STYLES.low;
  const usedOcr = result?.sources?.some((s) => s.ocr);

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
            placeholder="e.g. antimony oxide pigment for industrial paint, or rubber coated fabric for a fuel pump diaphragm"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSearch();
            }}
          />

          <div className="mt-4 flex items-center justify-between">
            <button
              onClick={() => handleSearch()}
              disabled={loading}
              className="bg-red-800 hover:bg-red-900 disabled:bg-gray-400 text-white text-sm font-medium px-5 py-2.5 rounded shadow-sm transition-colors"
            >
              {loading ? 'Searching standards...' : 'Find Standards'}
            </button>
            <span className="text-xs text-gray-400">Ctrl+Enter to search</span>
          </div>

          <div className="mt-4 pt-4 border-t flex flex-wrap items-center gap-2 text-xs text-gray-500">
            <span>Try an example:</span>
            {['antimony oxide for paints', 'fuel pump diaphragm fabric', 'paint'].map((item) => (
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

        {/* Clarification */}
        {result?.clarification_needed && (
          <div className="mt-6 bg-amber-50 border border-amber-300 p-5 rounded-lg">
            <p className="text-sm font-semibold text-amber-900 mb-3">{result.message}</p>
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
              <div className={'text-xs px-2.5 py-1 rounded border font-medium text-right ' + confidence.className}>
                <div>{confidence.label}</div>
                <div className="font-normal opacity-80">{confidence.note}</div>
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
                        <span className="block text-gray-600">{s.role}</span>
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
      </main>

      <footer className="max-w-4xl mx-auto px-4 pb-10 text-xs text-gray-500">
        PRISM is a decision-support prototype. Recommendations are not a
        determination of legal or contractual compliance, and certification
        requirements must be verified against current BIS listings.
      </footer>
    </div>
  );
}
