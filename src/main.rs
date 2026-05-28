use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

fn main() -> std::io::Result<()> {
    let port = env::var("PORT").unwrap_or_else(|_| "10000".to_string());
    let listener = TcpListener::bind(format!("0.0.0.0:{port}"))?;
    println!("VATrecover web interface listening on 0.0.0.0:{port}");

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                if let Err(error) = handle_client(stream) {
                    eprintln!("request failed: {error}");
                }
            }
            Err(error) => eprintln!("connection failed: {error}"),
        }
    }

    Ok(())
}

fn handle_client(mut stream: TcpStream) -> std::io::Result<()> {
    let mut buffer = [0; 2048];
    let size = stream.read(&mut buffer)?;
    let request = String::from_utf8_lossy(&buffer[..size]);
    let path = request
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("/");

    if path == "/health" {
        respond(
            &mut stream,
            "200 OK",
            "application/json",
            r#"{"status":"ok","service":"vatrecover"}"#,
        )
    } else {
        respond(&mut stream, "200 OK", "text/html; charset=utf-8", html())
    }
}

fn respond(stream: &mut TcpStream, status: &str, content_type: &str, body: &str) -> std::io::Result<()> {
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.as_bytes().len()
    );
    stream.write_all(response.as_bytes())
}

fn html() -> &'static str {
    r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VATrecover</title>
  <style>
    :root {
      --ink: #172033;
      --muted: #637083;
      --line: #d8dee8;
      --panel: #ffffff;
      --xero: #13b5ea;
      --sage: #00a376;
      --pastel: #6b6fd6;
      --risk: #b45309;
      --recover: #0f766e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: #eef2f6;
      letter-spacing: 0;
    }
    .app { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
    aside { background: #152033; color: #e8edf5; padding: 22px 18px; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 20px; margin-bottom: 28px; }
    .mark {
      width: 34px; height: 34px; border-radius: 7px;
      background: linear-gradient(135deg, var(--xero), var(--sage));
      display: grid; place-items: center; color: #fff; font-weight: 800;
    }
    nav a {
      display: flex; align-items: center; gap: 10px; color: #b8c2d1; text-decoration: none;
      padding: 10px 11px; border-radius: 6px; margin: 4px 0; font-size: 14px;
    }
    nav a.active, nav a:hover { color: #fff; background: rgba(255,255,255,.09); }
    .main { min-width: 0; }
    header {
      background: var(--panel); border-bottom: 1px solid var(--line); padding: 18px 28px;
      display: flex; align-items: center; justify-content: space-between; gap: 16px;
    }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .subtle { color: var(--muted); font-size: 13px; }
    .source-tabs { display: flex; gap: 8px; flex-wrap: wrap; }
    .tab {
      border: 1px solid var(--line); background: #fff; border-radius: 6px; padding: 8px 12px;
      font-weight: 650; font-size: 13px; color: var(--ink);
    }
    .tab.xero { border-color: var(--xero); color: #087ca3; }
    .tab.sage { border-color: var(--sage); color: #087958; }
    .tab.pastel { border-color: var(--pastel); color: #4b4fa9; }
    .content { padding: 22px 28px 34px; }
    .toolbar {
      display: grid; grid-template-columns: minmax(240px, 1.4fr) repeat(3, minmax(140px, .7fr)) auto;
      gap: 12px; align-items: end; background: var(--panel); border: 1px solid var(--line);
      border-radius: 8px; padding: 16px; margin-bottom: 16px;
    }
    label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; font-weight: 650; }
    select, input {
      width: 100%; min-height: 38px; border: 1px solid #c9d2df; border-radius: 6px;
      padding: 8px 10px; color: var(--ink); background: #fff; font: inherit;
    }
    button {
      min-height: 38px; border: 0; border-radius: 6px; padding: 0 15px;
      background: #0f62a4; color: #fff; font-weight: 700; cursor: pointer; white-space: nowrap;
    }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .metric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
    .metric strong { display: block; font-size: 24px; margin-top: 4px; }
    .metric.recover strong { color: var(--recover); }
    .metric.risk strong { color: var(--risk); }
    .workspace { display: grid; grid-template-columns: 1fr 320px; gap: 16px; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
    .panel-head {
      padding: 13px 15px; border-bottom: 1px solid var(--line);
      display: flex; align-items: center; justify-content: space-between;
    }
    .panel-head h2 { font-size: 15px; margin: 0; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 11px 12px; border-bottom: 1px solid #edf0f4; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; background: #fafbfc; }
    .amount { text-align: right; font-variant-numeric: tabular-nums; }
    .badge {
      display: inline-block; padding: 3px 7px; border-radius: 999px;
      background: #eef6ff; color: #075985; font-weight: 700; font-size: 12px;
    }
    .connector {
      padding: 14px 15px; border-bottom: 1px solid #edf0f4;
      display: grid; grid-template-columns: 12px 1fr auto; gap: 10px; align-items: center;
    }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--xero); }
    .dot.sage { background: var(--sage); }
    .dot.pastel { background: var(--pastel); }
    .status { color: var(--muted); font-size: 12px; }
    .linklike { border: 1px solid var(--line); background: #fff; color: var(--ink); }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      aside { display: none; }
      .toolbar, .workspace { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      header { align-items: flex-start; flex-direction: column; }
    }
    @media (max-width: 560px) {
      .content, header { padding-left: 16px; padding-right: 16px; }
      .metrics { grid-template-columns: 1fr; }
      table { font-size: 12px; }
      th, td { padding: 9px 8px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <div class="brand"><div class="mark">V</div><span>VATrecover</span></div>
      <nav>
        <a class="active" href="#">Review Workbench</a>
        <a href="#">Client Organisations</a>
        <a href="#">Connectors</a>
        <a href="#">Working Papers</a>
        <a href="#">Configuration</a>
      </nav>
    </aside>
    <main class="main">
      <header>
        <div>
          <h1>Input VAT Recovery Review</h1>
          <div class="subtle">Multi-client review control for Xero, Sage Accounting, and Sage Pastel exports</div>
        </div>
        <div class="source-tabs">
          <button class="tab xero">Xero</button>
          <button class="tab sage">Sage</button>
          <button class="tab pastel">Pastel</button>
        </div>
      </header>
      <section class="content">
        <form class="toolbar">
          <div>
            <label for="client">Client organisation</label>
            <select id="client"><option>Example SME (Pty) Ltd</option></select>
          </div>
          <div>
            <label for="source">Source</label>
            <select id="source"><option>Xero</option><option>Sage Accounting</option><option>Pastel CSV/XLSX</option></select>
          </div>
          <div><label for="from">From</label><input id="from" type="date" value="2021-05-28"></div>
          <div><label for="to">To</label><input id="to" type="date" value="2026-05-28"></div>
          <button type="button">Run Review</button>
        </form>
        <div class="metrics">
          <div class="metric recover"><span class="subtle">Potential recovery</span><strong>R 400.00</strong></div>
          <div class="metric"><span class="subtle">Review items</span><strong>2</strong></div>
          <div class="metric"><span class="subtle">Period coverage</span><strong>5 yrs</strong></div>
          <div class="metric risk"><span class="subtle">Needs sign-off</span><strong>2</strong></div>
        </div>
        <div class="workspace">
          <section class="panel">
            <div class="panel-head">
              <h2>Review Items</h2>
              <button class="linklike" type="button">Export Working Paper</button>
            </div>
            <table>
              <thead><tr><th>Source</th><th>Supplier</th><th>Account</th><th>Reason</th><th class="amount">Under-claim</th><th>Review</th></tr></thead>
              <tbody>
                <tr>
                  <td><span class="badge">Xero</span></td>
                  <td>VAT Vendor<br><span class="subtle">4123456789</span></td>
                  <td>400 Materials</td>
                  <td>Supplier VAT number with zero VAT claim</td>
                  <td class="amount">R 300.00</td>
                  <td>Open</td>
                </tr>
                <tr>
                  <td><span class="badge">Pastel</span></td>
                  <td>VAT Vendor<br><span class="subtle">4123456789</span></td>
                  <td>400 Materials</td>
                  <td>Low effective VAT rate against pattern</td>
                  <td class="amount">R 100.00</td>
                  <td>Open</td>
                </tr>
              </tbody>
            </table>
          </section>
          <section class="panel">
            <div class="panel-head"><h2>Connectors</h2></div>
            <div class="connector"><span class="dot"></span><div><strong>Xero Accounting</strong><div class="status">OAuth 2.0, tenant scoped</div></div><button class="linklike">Manage</button></div>
            <div class="connector"><span class="dot sage"></span><div><strong>Sage Accounting</strong><div class="status">OAuth 2.0, business scoped</div></div><button class="linklike">Manage</button></div>
            <div class="connector"><span class="dot pastel"></span><div><strong>Sage Pastel</strong><div class="status">CSV/XLSX import ready</div></div><button class="linklike">Import</button></div>
          </section>
        </div>
      </section>
    </main>
  </div>
</body>
</html>"#
}
