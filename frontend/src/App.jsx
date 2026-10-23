import React from 'react';
import { useMemo, useState } from 'react';
import {
  AlertCircle, ArrowUpRight, BadgeCheck, Check, CheckCircle2, CircleHelp,
  ClipboardCheck, ImagePlus, LoaderCircle, RotateCcw, ShieldCheck, Upload,
  XCircle
} from 'lucide-react';

const DEFAULT_REQUIREMENTS = [
  'A Bajaj banner is visible and readable.',
  'Exactly two staff members are visible and both are wearing blue T-shirts.',
  'A Bajaj vehicle is visible.',
  'At least one customer is visible.'
];

const statusMeta = {
  pass: { label: 'Pass', icon: CheckCircle2, className: 'pass' },
  fail: { label: 'Fail', icon: XCircle, className: 'fail' },
  uncertain: { label: 'Needs review', icon: CircleHelp, className: 'uncertain' }
};

function App() {
  const [requirementsText, setRequirementsText] = useState(DEFAULT_REQUIREMENTS.join('\n'));
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState('');
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const requirements = useMemo(
    () => requirementsText.split('\n').map((line) => line.trim()).filter(Boolean),
    [requirementsText]
  );

  function selectFile(nextFile) {
    if (!nextFile) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(nextFile.type)) {
      setError('Please choose a JPG, PNG, or WEBP image.');
      return;
    }
    if (nextFile.size > 10 * 1024 * 1024) {
      setError('Image must be smaller than 10 MB.');
      return;
    }
    setFile(nextFile);
    setPreview(URL.createObjectURL(nextFile));
    setReport(null);
    setError('');
  }

  async function analyze(event) {
    event.preventDefault();
    setError('');
    setReport(null);
    if (!file) {
      setError('Upload a photo before checking compliance.');
      return;
    }
    if (!requirements.length) {
      setError('Add at least one requirement.');
      return;
    }

    setLoading(true);
    const form = new FormData();
    form.append('image', file);
    form.append('requirements', JSON.stringify(requirements));

    try {
      const response = await fetch('http://127.0.0.1:8000/analyze', {
        method: 'POST',
        body: form
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Could not analyze this image.');
      setReport(data);
    } catch (err) {
      setError(err.message || 'Could not connect to the backend. Is FastAPI running?');
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setFile(null);
    setPreview('');
    setReport(null);
    setError('');
  }

  const overall = report?.overall_status;
  const overallMeta = overall === 'compliant'
    ? { label: 'Compliant', className: 'pass', icon: BadgeCheck }
    : overall === 'not_compliant'
      ? { label: 'Not compliant', className: 'fail', icon: XCircle }
      : { label: 'Needs review', className: 'uncertain', icon: CircleHelp };

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Visual Check home">
          <span className="brand-mark"><ShieldCheck size={21} /></span>
          <span>Visual<span className="brand-light">Check</span></span>
        </a>
        <span className="topbar-tag"><span className="live-dot" /> AI INSPECTION MVP</span>
      </header>

      <main className="main-content">
        <section className="hero">
          <div className="eyebrow"><span className="eyebrow-line" /> IMAGE COMPLIANCE</div>
          <h1>Check the photo.<br /><span>Know what to fix.</span></h1>
          <p>Compare a photo against your visual standards and get a clear, requirement-by-requirement inspection report.</p>
        </section>

        <form className="workspace" onSubmit={analyze}>
          <section className="panel requirements-panel">
            <div className="panel-heading">
              <div className="step-number">01</div>
              <div>
                <h2>Define requirements</h2>
                <p>One requirement per line. Make each one specific.</p>
              </div>
            </div>
            <label className="field-label" htmlFor="requirements">PHOTO CHECKLIST <span>{requirements.length} checks</span></label>
            <textarea
              id="requirements"
              value={requirementsText}
              onChange={(e) => setRequirementsText(e.target.value)}
              rows={7}
              placeholder="Enter one requirement per line..."
            />
            <div className="helper"><AlertCircle size={14} /> Use visible, verifiable criteria such as object count, uniform colour, and readable signage.</div>
            <button type="button" className="text-button" onClick={() => setRequirementsText(DEFAULT_REQUIREMENTS.join('\n'))}>
              <RotateCcw size={14} /> Restore Bajaj example
            </button>
          </section>

          <section className="panel upload-panel">
            <div className="panel-heading">
              <div className="step-number">02</div>
              <div>
                <h2>Upload photo</h2>
                <p>Use a clear photo where the required details are visible.</p>
              </div>
            </div>

            <label className={`dropzone ${preview ? 'has-preview' : ''}`} htmlFor="photo">
              {preview ? (
                <>
                  <img className="preview-image" src={preview} alt="Selected photo preview" />
                  <span className="preview-overlay"><ImagePlus size={16} /> Change photo</span>
                </>
              ) : (
                <div className="drop-content">
                  <span className="upload-icon"><Upload size={22} /></span>
                  <strong>Choose a photo to inspect</strong>
                  <span>JPG, PNG or WEBP · up to 10 MB</span>
                  <span className="browse-button">Browse files <ArrowUpRight size={14} /></span>
                </div>
              )}
            </label>
            <input
              id="photo"
              className="visually-hidden"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => selectFile(e.target.files?.[0])}
            />
            {file && <div className="file-row"><Check size={15} /><span>{file.name}</span><button type="button" onClick={reset} aria-label="Remove selected photo"><XCircle size={16} /></button></div>}
            <div className="privacy-note"><ShieldCheck size={15} /> Your API key stays on the backend. Only the selected image is sent for analysis.</div>
            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? <><LoaderCircle className="spin" size={18} /> Checking image...</> : <><ClipboardCheck size={18} /> Check photo <ArrowUpRight size={16} /></>}
            </button>
          </section>
        </form>

        {error && <div className="error-banner"><AlertCircle size={18} /><span>{error}</span></div>}

        {report && (
          <section className="results-section">
            <div className="results-heading">
              <div>
                <div className="eyebrow"><span className="eyebrow-line" /> INSPECTION RESULTS</div>
                <h2>Your compliance report</h2>
              </div>
              <span className={`overall-pill ${overallMeta.className}`}><overallMeta.icon size={17} /> {overallMeta.label}</span>
            </div>
            <p className="report-summary">{report.summary}</p>
            <div className="score-strip">
              {[
                { label: 'Passed', count: report.findings.filter(f => f.status === 'pass').length, className: 'pass' },
                { label: 'Failed', count: report.findings.filter(f => f.status === 'fail').length, className: 'fail' },
                { label: 'Review', count: report.findings.filter(f => f.status === 'uncertain').length, className: 'uncertain' }
              ].map(item => (
                <div className="score-cell" key={item.label}>
                  <span className={`score-dot ${item.className}`} />
                  <span>{item.label}</span>
                  <strong>{item.count}</strong>
                </div>
              ))}
            </div>
            <div className="findings-list">
              {report.findings.map((finding, index) => {
                const meta = statusMeta[finding.status] || statusMeta.uncertain;
                const Icon = meta.icon;
                return (
                  <article className="finding-card" key={`${finding.requirement}-${index}`}>
                    <div className={`finding-icon ${meta.className}`}><Icon size={20} /></div>
                    <div className="finding-content">
                      <div className="finding-topline">
                        <h3>{finding.requirement}</h3>
                        <span className={`status-label ${meta.className}`}>{meta.label}</span>
                      </div>
                      <p>{finding.observed}</p>
                      {finding.correction && <div className="correction"><strong>Recommended correction</strong><span>{finding.correction}</span></div>}
                      <span className="confidence">Model confidence: {finding.confidence}</span>
                    </div>
                  </article>
                );
              })}
            </div>
            <div className="review-note"><CircleHelp size={16} /><span>AI results can be wrong. Review uncertain findings manually before approving or rejecting a photo.</span></div>
          </section>
        )}

        <footer className="footer">
          <span>VisualCheck <span className="footer-dot">·</span> Prototype</span>
          <span>Vision AI <span className="footer-dot">+</span> structured output</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
