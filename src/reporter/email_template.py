"""
邮件 HTML 模板 — 将报告 HTML 片段包装为带完整 CSS 的邮件页面
CSS 与网页端保持一致（深色主题）
"""


def get_report_css() -> str:
    """返回报告所需的 CSS 样式（与 web/app.py 保持一致）"""
    return """
:root {
    --bg: #0d1117;
    --bg-card: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --accent-green: #3fb950;
    --accent-orange: #d2991d;
    --accent-purple: #a371f7;
    --accent-red: #f85149;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    min-height: 100vh;
}
.custom-container { max-width: 1100px; margin: 0 auto; }
.report-header {
    text-align: center;
    padding: 24px 16px 16px;
    border-bottom: 1px solid #30363d;
    margin-bottom: 20px;
}
.report-header h1 {
    font-size: 1.6em;
    color: #c9d1d9;
    margin-bottom: 8px;
}
.report-header .date {
    color: #58a6ff;
    font-size: 0.7em;
    font-weight: normal;
}
.report-meta {
    color: #8b949e;
    font-size: 0.8em;
}
.summary-bar {
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
    margin-bottom: 24px;
}
.summary-item {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px 20px;
    text-align: center;
    min-width: 100px;
}
.summary-item .num {
    display: block;
    font-size: 1.6em;
    font-weight: 600;
    color: #58a6ff;
}
.summary-item .label {
    display: block;
    font-size: 0.75em;
    color: #8b949e;
    margin-top: 4px;
}
.report-section {
    margin-bottom: 32px;
    padding: 20px;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
}
.report-section h2 {
    font-size: 1.2em;
    color: #c9d1d9;
    margin-bottom: 6px;
}
.report-section .icon { font-size: 1.1em; }
.report-section .subtitle {
    color: #8b949e;
    font-size: 0.85em;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px dashed #30363d;
}
.status-indicator {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.78em;
    padding: 2px 8px;
    border-radius: 10px;
    white-space: nowrap;
}
.status-indicator .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}
.status-active { background: rgba(63, 185, 80, 0.12); color: #3fb950; }
.status-active .dot { background: #3fb950; }
.status-moderate { background: rgba(210, 153, 29, 0.12); color: #d2991d; }
.status-moderate .dot { background: #d2991d; }
.status-inactive { background: rgba(248, 81, 73, 0.12); color: #f85149; }
.status-inactive .dot { background: #f85149; }
.status-archived { background: rgba(139, 148, 158, 0.12); color: #8b949e; }
.status-archived .dot { background: #8b949e; }
.tag-capsule {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.72em;
    font-weight: 500;
    line-height: 1.5;
    white-space: nowrap;
}
.tag-new { background: rgba(255, 159, 28, 0.15); color: #ff9f1c; border: 1px solid rgba(255, 159, 28, 0.3); }
.tag-focus { background: rgba(88, 166, 255, 0.12); color: #58a6ff; border: 1px solid rgba(88, 166, 255, 0.25); }
.tag-burst { background: rgba(210, 153, 29, 0.12); color: #d2991d; border: 1px solid rgba(210, 153, 29, 0.25); }
.tag-quality { background: rgba(63, 185, 80, 0.12); color: #3fb950; border: 1px solid rgba(63, 185, 80, 0.25); }
.tag-trap { background: rgba(248, 81, 73, 0.12); color: #f85149; border: 1px solid rgba(248, 81, 73, 0.25); }
.tag-longterm { background: rgba(63, 185, 80, 0.12); color: #3fb950; border: 1px solid rgba(63, 185, 80, 0.25); }
.score-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.75em;
    font-weight: 600;
    background: rgba(255, 255, 255, 0.04);
}
.score-burst { color: #d2991d; }
.score-quality { color: #3fb950; }
.score-ai { color: #a371f7; }
.metric-row {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    align-items: center;
    font-size: 0.82em;
    color: #8b949e;
    margin-bottom: 8px;
}
.metric-item {
    display: inline-flex;
    align-items: center;
    gap: 4px;
}
.custom-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
}
.custom-card .repo-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
}
.custom-card .repo-rank {
    background: #58a6ff;
    color: #fff;
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.8em;
    font-weight: 600;
}
.custom-card .repo-name {
    color: #58a6ff;
    text-decoration: none;
    font-weight: 600;
    font-size: 1em;
}
.custom-card .repo-desc {
    color: #c9d1d9;
    font-size: 0.88em;
    line-height: 1.5;
    margin-bottom: 10px;
}
.repo-tags {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}
.repo-scores {
    margin-top: 8px;
    color: #58a6ff;
    font-size: 0.8em;
    font-weight: 500;
}
.dimensions {
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 0;
    margin-top: 10px;
    overflow: hidden;
}
.dim-title {
    color: #58a6ff;
    font-size: 0.85em;
    font-weight: 600;
    padding: 8px 12px;
    background: rgba(88, 166, 255, 0.05);
    border-bottom: 1px solid #30363d;
}
.dim-item {
    display: grid;
    grid-template-columns: 24px 80px 1fr;
    gap: 8px;
    align-items: start;
    padding: 8px 12px;
    font-size: 0.82em;
    line-height: 1.5;
    border-bottom: 1px solid rgba(48, 54, 61, 0.5);
}
.dim-item:last-child { border-bottom: none; }
.dim-icon { font-size: 1em; }
.dim-label { color: #8b949e; font-weight: 500; }
.dim-text { color: #c9d1d9; word-break: break-word; }
.dashboard-block { padding: 20px; }
.dashboard-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
.dashboard-item {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}
.dash-num {
    font-size: 1.8em;
    font-weight: 700;
    color: #58a6ff;
}
.dash-label {
    font-size: 0.78em;
    color: #8b949e;
    margin-top: 4px;
}
.lang-distribution {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px dashed #30363d;
}
.lang-distribution h3 {
    font-size: 0.95em;
    color: #c9d1d9;
    margin-bottom: 12px;
}
.lang-bar-item {
    display: grid;
    grid-template-columns: 80px 1fr 40px;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
    font-size: 0.82em;
}
.lang-name { color: #c9d1d9; }
.lang-bar-bg {
    background: #0d1117;
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
    border: 1px solid #30363d;
}
.lang-bar-fill {
    background: linear-gradient(90deg, #58a6ff, #79c0ff);
    height: 100%;
}
.lang-count { color: #8b949e; text-align: right; }
.query-info {
    margin-top: 16px;
    padding: 12px;
    background: #0d1117;
    border-radius: 8px;
    font-size: 0.82em;
    color: #8b949e;
    line-height: 1.7;
}
.query-info strong { color: #c9d1d9; }
.health-progress {
    margin-top: 6px;
    padding: 8px 12px;
    border-top: 1px dashed #30363d;
}
.health-progress-bar {
    height: 6px;
    border-radius: 3px;
    background: #0d1117;
    overflow: hidden;
    margin-top: 4px;
}
.health-progress-fill {
    height: 100%;
    border-radius: 3px;
}
.health-progress-fill.active { background: #3fb950; }
.health-progress-fill.moderate { background: #d2991d; }
.health-progress-fill.inactive { background: #f85149; }
.health-progress-label {
    font-size: 0.75em;
    color: #8b949e;
    margin-top: 4px;
}
.empty-state {
    text-align: center;
    padding: 20px;
    color: #8b949e;
    font-size: 0.85em;
    border: 1px dashed #30363d;
    border-radius: 8px;
    margin: 8px 0;
}
.fallback-banner {
    background: rgba(88, 166, 255, 0.08);
    border: 1px solid rgba(88, 166, 255, 0.25);
    color: #58a6ff;
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 0.85em;
    line-height: 1.6;
}
footer {
    text-align: center;
    color: #8b949e;
    font-size: 0.78em;
    padding: 24px 16px;
    border-top: 1px solid #30363d;
    margin-top: 32px;
}
"""


def wrap_html_for_email(report_html: str) -> str:
    """将报告 HTML 片段包装为完整的邮件 HTML（含 CSS 样式）

    与网页端深色主题保持一致
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
{get_report_css()}
</style>
</head>
<body>
{report_html}
</body>
</html>"""
