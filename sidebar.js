/**
 * SSF Aquatics — Shared Sidebar
 * Usage: <script src="sidebar.js"></script>
 * Then call: injectSidebar('leaderboard') with the active page key
 */

const SIDEBAR_STYLES = `
  :root {
    --deep:#071429; --navy:#0B1F3A; --panel:#0D1E38; --mid:#2196F3;
    --light:#64B5F6; --gold:#F9A825; --white:#F0F6FF; --grey:#8BA3C0;
    --border:rgba(33,150,243,0.12); --hover:rgba(33,150,243,0.06);
    --sidebar:220px;
  }
  html,body { height:100%; margin:0; padding:0; overflow:hidden; }
  body {
    background:var(--deep); color:var(--white);
    font-family:'DM Sans',sans-serif; font-weight:300;
    display:flex;
  }
  .ssf-sidebar {
    width:var(--sidebar); flex-shrink:0;
    background:var(--panel); border-right:1px solid var(--border);
    display:flex; flex-direction:column;
    height:100vh; overflow-y:auto;
  }
  .ssf-sidebar-brand {
    padding:1.25rem 1.1rem .9rem;
    border-bottom:1px solid var(--border);
    text-decoration:none; display:block;
  }
  .ssf-brand-name {
    font-family:'Bebas Neue',sans-serif; font-size:1.25rem;
    letter-spacing:.08em; color:var(--white); line-height:1;
  }
  .ssf-brand-sub {
    font-family:'DM Mono',monospace; font-size:.55rem;
    letter-spacing:.12em; color:var(--grey); text-transform:uppercase; margin-top:.2rem;
  }
  .ssf-nav-section { padding:.6rem 0; }
  .ssf-nav-label {
    font-family:'DM Mono',monospace; font-size:.52rem;
    letter-spacing:.18em; text-transform:uppercase;
    color:rgba(139,163,192,0.35); padding:.25rem 1.1rem;
  }
  .ssf-nav-item {
    display:flex; align-items:center; gap:.6rem;
    padding:.5rem 1.1rem; font-size:.83rem; color:var(--grey);
    text-decoration:none; transition:all .15s;
    border-left:2px solid transparent;
  }
  .ssf-nav-item:hover { color:var(--white); background:var(--hover); }
  .ssf-nav-item.active {
    color:var(--white); background:rgba(33,150,243,0.1);
    border-left-color:var(--mid);
  }
  .ssf-nav-icon { width:17px; text-align:center; flex-shrink:0; font-size:.9rem; }
  .ssf-nav-divider { height:1px; background:var(--border); margin:.4rem 1.1rem; }
  .ssf-main { flex:1; display:flex; flex-direction:column; height:100vh; overflow:hidden; }
  @media(max-width:768px) { .ssf-sidebar { display:none; } html,body { overflow:auto; } .ssf-main { height:auto; } }
`;

const NAV_ITEMS = [
  { section: 'Main', items: [
    { key:'dashboard',   icon:'&#9744;',   label:'Dashboard',   href:'dashboard.html' },
    { key:'times',       icon:'&#9203;',   label:'Times',       href:'times.html' },
    { key:'leaderboard', icon:'&#127942;', label:'Leaderboard', href:'leaderboard.html' },
    { key:'attendance',  icon:'&#9989;',   label:'Attendance',  href:'attendance.html' },
    { key:'dryland',     icon:'&#128170;', label:'Dryland',     href:'dryland.html' },
    { key:'time-standards', icon:'&#127941;', label:'Standards',  href:'time-standards.html' },
  ]},
  { section: 'Roster', items: [
    { key:'swimmers',    icon:'&#127946;', label:'Swimmers',    href:'times.html' },
    { key:'groups',      icon:'&#128101;', label:'Groups',      href:'groups.html' },
    { key:'parents',     icon:'&#128106;', label:'Parents',     href:'register.html' },
  ]},
  { section: 'Management', items: [
    { key:'coach-hub',   icon:'&#11088;',  label:'Coach Hub',   href:'coach-hub.html' },
    { key:'analytics',   icon:'&#128200;', label:'Analytics',   href:'coach-analytics.html' },
    { key:'account',     icon:'&#128273;', label:'My Account',  href:'dashboard.html' },
  ]},
];

function injectSidebar(activePage) {
  // Inject styles
  const style = document.createElement('style');
  style.textContent = SIDEBAR_STYLES;
  document.head.insertBefore(style, document.head.firstChild);

  // Build sidebar HTML
  let sectionsHtml = '';
  NAV_ITEMS.forEach((section, si) => {
    if (si > 0) sectionsHtml += '<div class="ssf-nav-divider"></div>';
    sectionsHtml += `<div class="ssf-nav-section">
      <div class="ssf-nav-label">${section.section}</div>
      ${section.items.map(item => `
        <a class="ssf-nav-item${item.key === activePage ? ' active' : ''}" href="${item.href}">
          <span class="ssf-nav-icon">${item.icon}</span>${item.label}
        </a>`).join('')}
    </div>`;
  });

  const sidebar = document.createElement('aside');
  sidebar.className = 'ssf-sidebar';
  sidebar.innerHTML = `
    <a class="ssf-sidebar-brand" href="index.html">
      <div class="ssf-brand-name">SSF Aquatics</div>
      <div class="ssf-brand-sub">Team Portal</div>
    </a>
    <nav>${sectionsHtml}</nav>
  `;

  // Wrap existing body content in .ssf-main
  const main = document.createElement('div');
  main.className = 'ssf-main';
  while (document.body.firstChild) {
    main.appendChild(document.body.firstChild);
  }
  document.body.appendChild(sidebar);
  document.body.appendChild(main);
}

// Auto-initialize — runs synchronously if DOM already parsed, else waits
function _sidebarInit() {
  const page = document.body && document.body.getAttribute('data-page');
  if (page) injectSidebar(page);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _sidebarInit);
} else {
  _sidebarInit();
}
