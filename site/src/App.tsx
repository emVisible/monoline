import { lang, setLang, t } from "./i18n";
import { Lead, Note, Rule, Scene } from "./components/Scene";
import { HeroCut } from "./components/HeroCut";
import { StageRail } from "./components/StageRail";
import { CountUp } from "./components/CountUp";
import { Playhead } from "./components/Playhead";
import { KINDS } from "./strings";

const REPO = "https://github.com/emVisible/monoline";
const SCENES = 7;

export default function App() {
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="masthead">
        <a className="brand" href="#top">
          <Logo />
          <span>Monoline</span>
        </a>
        <nav className="masthead__nav">
          <LangToggle />
          <a className="ghost" href={REPO}>{t("nav_source")}</a>
        </nav>
      </header>

      <main id="main">
        <Scene id="top" index={0} total={SCENES} eyebrow={t("hero_kicker")} align="center">
          <h1 className="display">
            <span>{t("hero_line1")}</span>
            <span>{t("hero_line2")}</span>
            <span className="accent">{t("hero_line3")}</span>
          </h1>
          <Rule />
          <Lead>{t("hero_sub")}</Lead>
          <HeroCut />
        </Scene>

        <Scene index={1} total={SCENES} eyebrow="02 · pipeline">
          <h2>{t("b2_title")}</h2>
          <Lead>{t("b2_sub")}</Lead>
          <StageRail />
          <Note>{t("b2_note")}</Note>
        </Scene>

        <Scene index={2} total={SCENES} eyebrow="03 · layouts">
          <h2>{t("b3_title")}</h2>
          <Lead>{t("b3_sub")}</Lead>
          <ul className="kinds">
            {KINDS.map((k) => <li key={k}>{k}</li>)}
          </ul>
          <Note>{t("b3_note")}</Note>
        </Scene>

        <Scene index={3} total={SCENES} eyebrow="04 · outline">
          <h2>{t("b4_title")}</h2>
          <Lead>{t("b4_sub")}</Lead>
          <figure className="frame">
            <img src="/frames/outline.png" alt="Monoline Studio: the beat list, a live preview and the per-beat inspector" width={1600} height={900} loading="lazy" />
            <figcaption>Studio · beats / preview / inspector</figcaption>
          </figure>
        </Scene>

        <Scene index={4} total={SCENES} eyebrow="05 · determinism" align="center">
          <h2>{t("b5_title")}</h2>
          <Lead>{t("b5_sub")}</Lead>
          <dl className="stats">
            <Stat to={140} label={t("b5_stat_tests")} />
            <Stat to={25} label={t("b5_stat_voices")} />
            <Stat to={158} label={t("b5_stat_icons")} />
            <Stat to={4} label={t("b5_stat_themes")} />
          </dl>
        </Scene>

        <Scene index={5} total={SCENES} eyebrow="06 · runtime">
          <h2>{t("b6_title")}</h2>
          <Lead>{t("b6_sub")}</Lead>
          <ul className="reqs">
            <li>{t("b6_req1")}</li><li>{t("b6_req2")}</li>
            <li>{t("b6_req3")}</li><li>{t("b6_req4")}</li>
          </ul>
          <Note>{t("b6_note")}</Note>
        </Scene>

        <Scene index={6} total={SCENES} eyebrow="07 · get it" align="center">
          <h2>{t("b7_title")}</h2>
          <div className="cmds">
            <div>
              <span className="cmds__label">{t("b7_step1")}</span>
              <code>make bootstrap</code>
            </div>
            <div>
              <span className="cmds__label">{t("b7_step2")}</span>
              <code>make start</code>
            </div>
          </div>
          <a className="cta" href={REPO}>{t("b7_cta")}</a>
          <Note>{t("b7_note")}</Note>
        </Scene>
      </main>

      <footer className="footer">
        <span>{t("footer")}</span>
        <span className="footer__meta">MIT · macOS / Linux</span>
      </footer>

      <Playhead scenes={SCENES} />
    </>
  );
}

function Stat({ to, label }: { to: number; label: string }) {
  return (
    <div className="stat">
      <dt><CountUp to={to} /></dt>
      <dd>{label}</dd>
    </div>
  );
}

function LangToggle() {
  const current = lang();
  return (
    <span className="lang" role="group" aria-label="Language">
      {(["en", "zh"] as const).map((l) => (
        <button key={l} type="button" aria-pressed={current === l} onClick={() => setLang(l)}>
          {l === "en" ? "EN" : "中文"}
        </button>
      ))}
    </span>
  );
}

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2.5" y="2.5" width="19" height="19" rx="5.5" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9.5 8.2 L16 12 L9.5 15.8 Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="20.5" cy="3.5" r="2.1" fill="var(--accent)" />
    </svg>
  );
}
