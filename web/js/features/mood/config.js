/* Royal Abendregie: progressive, erklärbare Film- und Serienkuratierung. */
export const MOOD_MATCH_STEPS = [
  {
    key: "format", word: "FORMAT", title: "Was soll heute laufen?",
    copy: "Erst der Rahmen, dann die Feinheiten. Nach dieser Wahl kannst du schon direkt kuratieren.",
    options: [
      { value: "movie", icon: "01", title: "Ein Film", copy: "Ein Abend, eine Geschichte, ein Ende" },
      { value: "series", icon: "02", title: "Eine Serie", copy: "Eine Folge oder der Anfang von mehr" },
      { value: "any", icon: "∞", title: "Beides offen", copy: "Der stärkste Treffer entscheidet" },
    ],
  },
  {
    key: "mood", word: "WIRKUNG", title: "Was soll der Titel mit dir machen?",
    copy: "Wähle eine Wirkung – oder lass nur den Genre-Kompass entscheiden. Dort kannst du bis in jedes Genre hinein schärfen.",
    options: [
      { value: "pulse", icon: "↗", title: "Mich fesseln", copy: "Druck, Tempo und keine Leerlaufminute" },
      { value: "shadow", icon: "◐", title: "Dunkel abtauchen", copy: "Unbehagen, Rätsel und Gänsehaut" },
      { value: "laugh", icon: ":)", title: "Mich aufheitern", copy: "Leicht, klug oder herrlich albern" },
      { value: "wonder", icon: "✦", title: "Mich staunen lassen", copy: "Große Welten und starke Bilder" },
      { value: "heart", icon: "♥", title: "Mich berühren", copy: "Nähe, Gefühl und Figuren, die bleiben" },
      { value: "comfort", icon: "≈", title: "Mich runterbringen", copy: "Warm, zugänglich und ohne schwere Kante" },
      { value: "real", icon: "◎", title: "Wirklichkeit sehen", copy: "Dokumentarisch, historisch und nah an echten Welten" },
      { value: "raw", icon: "◆", title: "Kante spüren", copy: "Konflikt, Moral und Geschichten mit rauer Oberfläche" },
      { value: "rhythm", icon: "♫", title: "Im Rhythmus bleiben", copy: "Musik, Bewegung und Bilder mit eigenem Puls" },
    ],
  },
  {
    key: "company", word: "RUNDE", title: "Für wen wird heute gespielt?",
    copy: "Die Runde verändert die Passung. Familienauswahl bleibt streng bei familientauglichen Genres.",
    options: [
      { value: "alone", icon: "1", title: "Nur für mich", copy: "Geschmack ohne Kompromisse" },
      { value: "couple", icon: "2", title: "Zu zweit", copy: "Gemeinsamer Sog statt kleinster Nenner" },
      { value: "friends", icon: "+", title: "Mit Freunden", copy: "Energie, Gesprächsstoff und starke Momente" },
      { value: "family", icon: "◆", title: "Familienrunde", copy: "Familie, Animation und Abenteuer ohne Horrortitel" },
    ],
  },
];

export const MOOD_MATCH_PROFILES = {
  pulse: {
    title: "Heute bleibt keine Minute liegen.",
    direct: ["Action", "Thriller", "Krimi", "Abenteuer"],
    related: ["Science-Fiction", "Mystery", "Krieg", "Western"],
    excluded: ["Familie", "Musik"],
    weights: { Action: 16, Thriller: 14, Krimi: 9, Abenteuer: 7, "Science-Fiction": 5 },
  },
  shadow: {
    title: "Das Licht bleibt besser an.",
    direct: ["Horror", "Mystery", "Thriller", "Krimi"],
    related: ["Science-Fiction", "Drama"],
    excluded: ["Familie", "Kinder", "Komödie", "Musik", "Romanze"],
    weights: { Horror: 17, Mystery: 14, Thriller: 11, Krimi: 7, Drama: 3 },
  },
  laugh: {
    title: "Leicht, aber nicht beliebig.",
    direct: ["Komödie"], related: ["Animation", "Familie", "Romanze", "Musik"],
    excluded: ["Horror", "Krieg"],
    weights: { Komödie: 18, Animation: 7, Familie: 5, Romanze: 4, Musik: 3 },
  },
  wonder: {
    title: "Eine andere Welt steht bereit.",
    direct: ["Science-Fiction", "Fantasy", "Abenteuer"],
    related: ["Animation", "Mystery", "Familie", "Action"], excluded: [],
    weights: { "Science-Fiction": 16, Fantasy: 15, Abenteuer: 10, Animation: 5, Mystery: 4 },
  },
  heart: {
    title: "Etwas, das länger bleibt.",
    direct: ["Drama", "Romanze", "Musik"], related: ["Komödie", "Familie", "Geschichte"],
    excluded: ["Horror"],
    weights: { Drama: 15, Romanze: 12, Musik: 7, Komödie: 4, Geschichte: 3 },
  },
  comfort: {
    title: "Der Abend darf weich landen.",
    direct: ["Komödie", "Familie", "Animation", "Romanze"],
    related: ["Abenteuer", "Drama", "Musik"],
    excluded: ["Horror", "Thriller", "Krimi", "Krieg"],
    weights: { Komödie: 14, Familie: 12, Animation: 10, Romanze: 8, Abenteuer: 4 },
  },
  real: {
    title: "Die Wirklichkeit schreibt den stärksten Schnitt.",
    direct: ["Dokumentation", "Geschichte"], related: ["Drama", "Musik", "Krieg"],
    excluded: ["Fantasy", "Horror"],
    weights: { Dokumentation: 18, Geschichte: 14, Drama: 7, Musik: 4, Krieg: 3 },
  },
  raw: {
    title: "Ein Abend mit Ecken und Nachhall.",
    direct: ["Krimi", "Krieg", "Western"], related: ["Drama", "Thriller", "Action", "Geschichte"],
    excluded: ["Familie", "Kinder"],
    weights: { Krimi: 15, Krieg: 14, Western: 14, Drama: 8, Thriller: 6, Action: 4 },
  },
  rhythm: {
    title: "Dieser Abend bewegt sich im eigenen Takt.",
    direct: ["Musik"], related: ["Animation", "Komödie", "Romanze", "Drama", "Dokumentation"],
    excluded: ["Horror", "Krieg"],
    weights: { Musik: 18, Animation: 8, Komödie: 6, Romanze: 5, Drama: 4, Dokumentation: 3 },
  },
};

export const MOOD_MATCH_RULES = MOOD_MATCH_PROFILES;
export const MOOD_DEFAULT_ANSWERS = { format: "any", mood: "open", company: "alone", genres: [] };
export const MOOD_REFINEMENT_GROUPS = [
  {
    key: "duration", title: "Zeitfenster", copy: "Unbekannte Laufzeiten zählen bei einem Limit nicht als Treffer.",
    options: [
      { value: "any", label: "Offen" }, { value: "90", label: "Bis 90 Min." },
      { value: "120", label: "Bis 2 Std." }, { value: "150", label: "Bis 2½ Std." },
    ],
  },
  {
    key: "tempo", title: "Tempo", copy: "Energie, nicht Härte.",
    options: [
      { value: "any", label: "Offen" }, { value: "quiet", label: "Ruhig" },
      { value: "balanced", label: "Im Fluss" }, { value: "drive", label: "Voller Zug" },
    ],
  },
  {
    key: "discovery", title: "Entdeckung", copy: "Sicherer Konsens oder Titel abseits der Masse.",
    options: [
      { value: "balanced", label: "Ausgewogen" }, { value: "safe", label: "Sicherer Treffer" },
      { value: "hidden", label: "Geheimtipp" }, { value: "surprise", label: "Überraschung" },
    ],
  },
  {
    key: "era", title: "Epoche", copy: "Das Erscheinungsjahr ist ein hartes Kriterium.",
    options: [
      { value: "any", label: "Alle Jahre" }, { value: "new", label: "Seit 2018" },
      { value: "modern", label: "2000–2017" }, { value: "classic", label: "Vor 2000" },
    ],
  },
  {
    key: "library", title: "Jellyfin", copy: "Nur eindeutige Bibliothekszustände werden berücksichtigt.",
    options: [
      { value: "any", label: "Alles" }, { value: "owned", label: "Sofort ansehen" },
      { value: "missing", label: "Neu entdecken" },
    ],
  },
  {
    key: "minRating", title: "Bewertung", copy: "Fehlende Bewertungen bestehen eine Mindestgrenze nicht.",
    options: [
      { value: "any", label: "Offen" }, { value: "7", label: "Ab 7,0" },
      { value: "8", label: "Ab 8,0" },
    ],
  },
];

export const MOOD_AVOID_GENRES = [
  "Horror", "Thriller", "Action", "Krimi", "Drama", "Romanze", "Komödie", "Animation", "Dokumentation",
];
export const MOOD_GENRE_COMPASS = [
  { name: "Action", code: "ACT" }, { name: "Abenteuer", code: "ADV" },
  { name: "Animation", code: "ANI" }, { name: "Dokumentation", code: "DOC" },
  { name: "Drama", code: "DRA" }, { name: "Familie", code: "FAM" },
  { name: "Fantasy", code: "FAN" }, { name: "Geschichte", code: "HIS" },
  { name: "Horror", code: "HOR" }, { name: "Kinder", code: "KID" },
  { name: "Komödie", code: "COM" }, { name: "Krimi", code: "CRI" },
  { name: "Krieg", code: "WAR" }, { name: "Musik", code: "MUS" },
  { name: "Mystery", code: "MYS" }, { name: "Nachrichten", code: "NEW" },
  { name: "Reality", code: "REA" }, { name: "Romanze", code: "ROM" },
  { name: "Science-Fiction", code: "SCI" }, { name: "Soap", code: "SOA" },
  { name: "Talk", code: "TLK" }, { name: "Thriller", code: "THR" },
  { name: "TV-Film", code: "TV" }, { name: "Western", code: "WES" },
];
export const MOOD_GENRE_ALIASES = {
  action: "Action", adventure: "Abenteuer", abenteuer: "Abenteuer", animation: "Animation",
  comedy: "Komödie", komödie: "Komödie", crime: "Krimi", krimi: "Krimi",
  documentary: "Dokumentation", dokumentarfilm: "Dokumentation", dokumentation: "Dokumentation",
  drama: "Drama", family: "Familie", familie: "Familie", kids: "Kinder", kinder: "Kinder",
  fantasy: "Fantasy", history: "Geschichte", geschichte: "Geschichte", horror: "Horror",
  music: "Musik", musik: "Musik", mystery: "Mystery", romance: "Romanze", romanze: "Romanze",
  news: "Nachrichten", nachrichten: "Nachrichten", reality: "Reality", soap: "Soap", talk: "Talk",
  "science fiction": "Science-Fiction", "science-fiction": "Science-Fiction", "sci-fi": "Science-Fiction",
  thriller: "Thriller", "tv movie": "TV-Film", "tv-film": "TV-Film",
  war: "Krieg", krieg: "Krieg", western: "Western",
};
