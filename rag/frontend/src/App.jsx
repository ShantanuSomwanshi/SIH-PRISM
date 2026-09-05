import React, { useState } from 'react';

export default function App() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async (textToSearch) => {
    const searchText = textToSearch || query;
    if (!searchText) return;
    setLoading(true);
    setResult(null);

    try {
      const res = await fetch('http://127.0.0.1:8000/api/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchText }),
      });
      const data = await res.json();
      setResult(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 font-sans">
      {/* Top Gov Header */}
      <div className="bg-white border-b px-8 py-2 flex justify-between text-xs text-gray-600">
        <span>Government of India portal concept</span>
        <span>English ▾</span>
      </div>

      {/* Main Nav */}
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

      {/* Content Area */}
      <main className="max-w-4xl mx-auto py-10 px-4">
        <div className="flex justify-between items-start mb-6">
          <div>
            <span className="text-xs font-semibold text-red-800 uppercase tracking-wider">BIS Digital Service Module</span>
            <h2 className="text-2xl font-bold text-gray-900 mt-1">PRISM — Procurement Recommendation for Indian Standards Matching</h2>
            <p className="text-sm text-gray-600 mt-1">Describe a product or paste a tender specification to identify applicable Indian Standards.</p>
          </div>
          <span className="bg-amber-50 text-amber-800 text-xs px-2.5 py-1 rounded border border-amber-200">Demo data — MVP</span>
        </div>

        {/* Input Card */}
        <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Describe the product or paste your specification
          </label>
          <textarea
            className="w-full border border-gray-300 rounded p-3 text-sm focus:outline-none focus:ring-2 focus:ring-red-900/20 focus:border-red-900"
            rows="4"
            placeholder="e.g. LED bulb for office corridor or Industrial safety helmet for construction site"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />

          <div className="mt-4 flex items-center justify-between">
            <button
              onClick={() => handleSearch()}
              disabled={loading}
              className="bg-red-800 hover:bg-red-900 text-white text-sm font-medium px-5 py-2.5 rounded shadow-sm transition-colors"
            >
              {loading ? 'Searching Standards...' : 'Find Standards'}
            </button>
          </div>

          {/* Quick Examples */}
          <div className="mt-4 pt-4 border-t flex items-center space-x-2 text-xs text-gray-500">
            <span>Try an example:</span>
            {['LED bulbs', 'PVC water pipes', 'Industrial safety helmet'].map((item) => (
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

        {/* Disambiguation UI */}
        {result?.clarification_needed && (
          <div className="mt-6 bg-amber-50 border border-amber-300 p-5 rounded-lg">
            <p className="text-sm font-semibold text-amber-900 mb-2">{result.message}</p>
            <div className="flex gap-2">
              {result.clarification_options.map((opt) => (
                <button
                  key={opt}
                  onClick={() => handleSearch(opt)}
                  className="bg-white border border-amber-400 px-3 py-1.5 rounded text-xs font-medium text-amber-900 hover:bg-amber-100"
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Recommendation Output Card */}
        {result && !result.clarification_needed && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex justify-between items-center border-b pb-3 mb-4">
              <h3 className="font-bold text-gray-900 text-base">Recommendation Summary</h3>
              {result.confidence_flag && (
                <span className="bg-green-50 text-green-700 text-xs px-2.5 py-0.5 rounded border border-green-200 font-medium">
                  Verified & Faithfully Grounded
                </span>
              )}
            </div>

            <div className="space-y-4 text-sm">
              <div>
                <span className="font-semibold text-gray-700">Primary Standard:</span>
                <p className="text-red-900 font-medium">{result.primary_standard} — {result.title}</p>
              </div>

              <div>
                <span className="font-semibold text-gray-700">Allied Standards:</span>
                <ul className="list-disc list-inside mt-1 text-gray-600 space-y-1">
                  {result.allied_standards?.map((s, idx) => (
                    <li key={idx}><span className="font-medium text-gray-800">{s.code}</span>: {s.role}</li>
                  ))}
                </ul>
              </div>

              <div>
                <span className="font-semibold text-gray-700">Version Status:</span>
                <p className="text-gray-600">{result.version_status}</p>
              </div>

              <div>
                <span className="font-semibold text-gray-700">Certification Requirement:</span>
                <p className="text-gray-600">{result.certification}</p>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}