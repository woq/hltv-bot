() => {
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

  const el = qs("#scoreboardElement");
  const ds = el ? { ...el.dataset } : {};

  const parsePlayerRaw = (raw) => {
    const m = raw.trim().match(/^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)/);
    if (!m) return null;
    return {
      nick: m[1],
      kills: Number(m[2]),
      assists: Number(m[3]),
      deaths: Number(m[4]),
      adr: Number(m[5]),
    };
  };

  const teams = qsa(".scoreboard .team").map((team) => {
    const name = (qs(".teamName", team)?.innerText || "").trim();
    const players = qsa("tr", team)
      .slice(1)
      .map((tr) => parsePlayerRaw(tr.innerText.replace(/\s+/g, " ")))
      .filter(Boolean);
    return { name, players };
  });

  const scoreText = (qs(".scoreboard .score.scoreText")?.innerText || "")
    .replace(/\s+/g, "")
    .replace(":", "-");
  const [ctScore, tScore] = scoreText.split("-").map((n) => Number(n) || 0);

  const log = qsa(".gamelog .gamelogBox").slice(0, 40).map((box) => {
    const cls = box.className;
    let type = "other";
    if (cls.includes("playerKill")) type = "kill";
    else if (cls.includes("winnerCT")) type = "round_over_ct";
    else if (cls.includes("winnerT") || cls.includes("winnerTERRORIST"))
      type = "round_over_t";
    else if (cls.includes("roundStart")) type = "round_start";
    else if (cls.includes("quitGame")) type = "quit";
    else if (/bomb/i.test(cls)) type = "bomb";

    const alts = qsa("img", box)
      .map((i) => i.alt || "")
      .filter(Boolean);
    const weaponSrc = qs('img[alt^="killed"]', box)?.src || "";
    const weapon = (weaponSrc.split("/").pop() || "").replace(/\.png$/, "");
    const hs = alts.some((a) => /headshot/i.test(a));
    const assist = alts.some((a) => /assist/i.test(a));
    return {
      type,
      text: box.innerText.replace(/\s+/g, " ").trim(),
      weapon,
      headshot: hs,
      assist,
      alts,
    };
  });

  const maps = qsa(".mapholder, .played").length
    ? qsa(".mapholder").map((m) => ({
        name: (qs(".mapname", m)?.innerText || "").trim(),
        text: m.innerText.replace(/\s+/g, " ").trim().slice(0, 80),
      }))
    : [];

  return {
    url: location.href,
    title: document.title,
    live: /\bLIVE\b/.test(document.body.innerText),
    maps,
    scorebotUrl: ds.scorebotUrl || "https://scorebot-lb.hltv.org",
    scorebotId: ds.scorebotId || null,
    team1: { name: ds.team1Name, id: ds.team1Id },
    team2: { name: ds.team2Name, id: ds.team2Id },
    csVersion: ds.csVersion || "CS2",
    roundText: qs(".currentRoundText")?.innerText?.trim() || null,
    ctScore,
    tScore,
    scoreText,
    teams,
    log,
    capturedAt: new Date().toISOString(),
  };
}
