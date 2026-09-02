// Typed client for the thebeast API. Shapes mirror thebeast/api/main.py.

export interface GameSchedule {
	game_id: string;
	date: string;
	home_team_id: string;
	away_team_id: string;
	venue_id: string;
	first_pitch: string | null;
	game_pk: number | null;
	status: 'Preview' | 'Live' | 'Final' | string | null;
	detailed_state: string | null;
	home_score: number | null;
	away_score: number | null;
	inning: number | null;
	inning_half: 'Top' | 'Bottom' | string | null;
}

export interface InningLine {
	num: number;
	away_runs: number | null;
	home_runs: number | null;
}

export interface TeamTotals {
	runs: number | null;
	hits: number | null;
	errors: number | null;
	left_on_base: number | null;
}

export interface GameSituation {
	balls: number | null;
	strikes: number | null;
	outs: number | null;
	on_first: boolean;
	on_second: boolean;
	on_third: boolean;
	batter: string | null;
	pitcher: string | null;
	/** Who's coming, not just who's up. The pitch forecast is about the at-bat
	 *  that hasn't started, so the on-deck hitter is the one it's for. */
	on_deck?: string | null;
	in_hole?: string | null;
}

export interface GameLinescore {
	game_id: string;
	innings: InningLine[];
	away_totals: TeamTotals;
	home_totals: TeamTotals;
	situation: GameSituation;
}

export interface BatterBoxLine {
	name: string;
	player_id: number | null;
	position: string | null;
	// Real batting-order slot (1-9) from MLB's own data — authoritative,
	// unlike at_bats which only correlates with it.
	lineup_slot: number | null;
	at_bats: number | null;
	hits: number | null;
	home_runs: number | null;
	rbi: number | null;
	walks: number | null;
	strikeouts: number | null;
}

export interface PitcherBoxLine {
	name: string;
	player_id: number | null;
	innings_pitched: string | null;
	pitches: number | null;
	hits_allowed: number | null;
	earned_runs: number | null;
	walks_allowed: number | null;
	strikeouts: number | null;
}

export interface TeamBoxscore {
	batters: BatterBoxLine[];
	pitchers: PitcherBoxLine[];
}

export interface GameBoxscore {
	game_id: string;
	away: TeamBoxscore;
	home: TeamBoxscore;
}

export interface Histogram {
	edges: number[];
	counts: number[];
}

export interface PlayerLine {
	team: string;
	player_id: number;
	name?: string;
	// This player's real batting-order slot (1-9), from the confirmed MLB
	// lineup or the roster fallback — the authoritative order, unlike PA
	// which only correlates with it.
	lineup_slot?: number;
	// Where he plays — "SS", "CF", "DH". Absent rather than guessed.
	position?: string;
	// 'lineup' — tonight's card, the only place a DH exists, since DH is an
	// assignment rather than a property of the player. 'roster' — his usual
	// position, used until the card is posted. Different claims, so the column
	// distinguishes them rather than blurring the two.
	position_source?: 'lineup' | 'roster';
	pa: number;
	ab: number;
	hits: number;
	singles: number;
	doubles: number;
	triples: number;
	home_runs: number;
	rbi: number;
	bb: number;
	hbp: number;
	k: number;
	ipo: number;
	[key: string]: number | string | undefined;
}

export interface PitcherLine {
	team: string;
	player_id: number;
	name?: string;
	// Projected per-game averages (the sim has no fielding errors, so er = runs).
	ip: number;
	bf: number;
	hits_allowed: number;
	hr_allowed: number;
	bb_allowed: number;
	k: number;
	er: number;
	runs_allowed: number;
	outs: number;
	// Projected pitch count for this outing.
	pitches: number;
	[key: string]: number | string | undefined;
}

export interface PlayLogEntry {
	half: 'Top' | 'Bot';
	inning: number;
	team: string;
	batter: string;
	pitcher: string;
	outcome: string;
	runs: number;
	runners: string;
	outs: number;
}

export interface RepresentativeGame {
	home_score: number;
	away_score: number;
	home_by_inning: number[];
	away_by_inning: number[];
	extra_innings: boolean;
	play_log: PlayLogEntry[];
}

export interface SimResult {
	game_id: string;
	home: string;
	away: string;
	n: number;
	home_win_probability: number;
	home_win_probability_raw: number | null;
	home_run_mean: number;
	home_run_median: number;
	home_run_p10: number;
	home_run_p90: number;
	away_run_mean: number;
	away_run_median: number;
	away_run_p10: number;
	away_run_p90: number;
	total_mean: number;
	total_median: number;
	total_p10: number;
	total_p90: number;
	extra_inning_pct: number;
	spread_mean: number;
	player_lines: PlayerLine[];
	pitcher_lines: PitcherLine[];
	histograms: {
		home_runs: Histogram;
		away_runs: Histogram;
		totals: Histogram;
	};
	representative: RepresentativeGame | null;
	// Present only on a conditioned run (a final score was requested).
	conditioned?: ConditionedMeta;
	// Whether each side's lineup is the MLB-confirmed card or a projected
	// (roster-based) fallback.
	lineups?: { home: LineupStatus; away: LineupStatus };
}

export interface LineupStatus {
	team: string | null;
	confirmed: boolean;
	confirmed_at: string | null;
}

export interface ConditionedMeta {
	target_away: number;
	target_home: number;
	matches: number;
	games_run: number;
}

// One statistic's projected-vs-actual comparison (runs, total, etc.).
export interface RangeCompare {
	actual: number;
	mean: number;
	median: number;
	p10: number;
	p90: number;
	within_range: boolean;
	error: number; // actual - mean
	// Distribution-based percentages (present on the accuracy endpoint).
	percentile?: number; // where the real value landed in the sim distribution
	centrality_pct?: number; // 100% at the median, 0% at the tails
	hit_pct?: number; // % of sims exactly on the real number
	over_pct?: number; // % of sims above it
	under_pct?: number; // % of sims below it
}

export interface AccuracyBatterRow {
	player_id: number;
	name: string;
	team: string;
	lineup_slot: number | null;
	// Overall (unconditioned) projection.
	base_hits: number | null;
	base_home_runs: number | null;
	base_rbi: number | null;
	// Averaged over the sims that ended on the real final score.
	proj_hits: number;
	proj_home_runs: number;
	proj_rbi: number;
	actual_hits: number | null;
	actual_home_runs: number | null;
	actual_rbi: number | null;
}

type StatPct = { hits?: number; home_runs?: number; rbi?: number };

export interface ScoreMatch {
	target_home: number;
	target_away: number;
	matches: number;
	games_run: number;
	match_rate: number; // fraction of sims that ended this exact score
	batters: AccuracyBatterRow[];
	batter_mae: StatPct;
	// % accuracy of the score-matched box score vs. the real one, per stat.
	batter_accuracy_pct: StatPct;
	// % agreement between the overall prediction and the score-matched sims.
	base_vs_match_pct: StatPct;
	has_boxscore: boolean;
}

export interface GameAccuracy {
	game_id: string;
	final: boolean;
	home?: string;
	away?: string;
	actual?: {
		home_runs: number;
		away_runs: number;
		total: number;
		winner: 'home' | 'away' | 'tie';
		status: string | null;
	};
	prediction?: {
		n: number;
		home_win_probability: number;
		predicted_winner: 'home' | 'away';
		actual_winner: 'home' | 'away' | 'tie';
		picked_winner: boolean | null;
		winner_prob: number;
		home_runs: RangeCompare;
		away_runs: RangeCompare;
		total: RangeCompare;
		spread: RangeCompare;
		spread_mean: number;
		actual_spread: number;
		exact_score_prob: number;
		accuracy_pct: {
			winner: number;
			total: number;
			spread: number;
			home_runs: number;
			away_runs: number;
		};
	};
	score_match: ScoreMatch | null;
}

// Simulation of the *rest* of a game already in progress.
export interface LiveSim {
	game_id: string;
	live: boolean;
	reason?: string; // why there's nothing to resume, when live is false
	home?: string;
	away?: string;
	n?: number;
	// The exact live snapshot the simulation resumed from.
	state?: {
		inning: number;
		half: 'top' | 'bottom';
		outs: number;
		on_first: boolean;
		on_second: boolean;
		on_third: boolean;
		home_score: number;
		away_score: number;
		batter: string | null;
		pitcher: string | null;
		home_due_up_slot: number;
		away_due_up_slot: number;
	};
	home_win_probability?: number;
	away_win_probability?: number;
	// Still level after 9 — i.e. the game goes to extra innings, which the
	// engine doesn't play out, so it's reported as its own outcome.
	extras_probability?: number;
	projected_final?: {
		home_mean: number;
		home_median: number;
		home_p10: number;
		home_p90: number;
		away_mean: number;
		away_median: number;
		away_p10: number;
		away_p90: number;
		total_mean: number;
		total_median: number;
	};
	runs_to_come?: { home: number; away: number };
	likely_finals?: { away: number; home: number; pct: number }[];
	player_lines?: PlayerLine[];
	pitcher_lines?: PitcherLine[];
}

export interface BestBet {
	game_id: string;
	away: string;
	home: string;
	first_pitch: string | null;
	market:
		| 'home_ml'
		| 'away_ml'
		| 'over'
		| 'under'
		| 'home_rl'
		| 'away_rl'
		| 'prop_over'
		| 'prop_under';
	selection: string;
	price: number;
	line: number | null;
	book: string | null;
	model_probability: number;
	implied_probability: number;
	edge: number;
	expected_value: number;
	kelly_pct: number;
	ci_low: number;
	ci_high: number;
	lineups_confirmed: boolean;
	n_sims: number;
	/** Which of the three panels this play belongs in. */
	category: 'game_line' | 'pitcher_prop' | 'batter_prop';
	/** True when the game is already under way — priced off the remaining
	 *  innings, and marked in the UI with a live indicator. */
	is_live: boolean;
	/** True when this clears the minimum edge and sizes a stake. Plays below
	 *  the bar are still listed, but must not read as recommendations. */
	has_edge: boolean;
	/** Player props only; null on the game markets. */
	player?: string | null;
	stat?: string | null;
}

export interface BestBetsReport {
	date: string;
	generated_at: string;
	games_considered: number;
	games_priced: number;
	bets: BestBet[];
	notes: string[];
	props_available: boolean;
	live_games: number;
	/** {category: how many plays cleared the bar} — lets the UI tell
	 *  "nothing qualified" apart from "this market wasn't available". */
	counts: Record<string, number>;
	/** {category: how many were priced at all} — distinguishes an empty panel
	 *  (nothing quoted) from a full one where nothing qualified. */
	priced_counts: Record<string, number>;
	cached?: boolean;
}

/** One stat's accuracy over a window. `bias` is signed (actual - projected),
 *  so a model that is consistently short reads differently from one that
 *  misses evenly in both directions. */
export interface StatAccuracy {
	n: number;
	mae: number;
	rmse: number;
	bias: number;
	proj_per_game: number;
	actual_per_game: number;
	exact_pct: number;
	accuracy_pct: number;
}

export type StatBlock = Record<string, StatAccuracy>;

export interface PositionAccuracy {
	position: string;
	players: number;
	stats: StatBlock;
}

export interface PlayerAccuracy {
	player_id: number;
	name: string;
	team: string;
	side: 'batter' | 'pitcher';
	position: string | null;
	games: number;
	stats: StatBlock;
}

export interface ScoredGameSummary {
	game_id: string;
	date: string;
	home: string;
	away: string;
	actual: { home_runs: number; away_runs: number; total: number; spread: number; winner: string };
	home_win_probability: number | null;
	picked_winner: boolean | null;
	predicted_total: number | null;
	total_error: number | null;
	total_covered: boolean | null;
	exact_score_pct: number | null;
	pregame: boolean;
}

export interface CalibrationBucket {
	range: string;
	n: number;
	predicted: number;
	actual: number;
}

/** One side of a prop: what we say, what the price says, and the gap. */
export interface PropSide {
	price: number;
	/** The payout multiple, e.g. 1.53x — null when the source posts no odds.
	 *  A PrizePicks pick has no price of its own, so there is no multiple to
	 *  show and inventing one would put a payout on the card that nobody
	 *  offers. */
	multiplier: number | null;
	/** Our simulation's probability this side hits. */
	model_pct: number;
	/** The bar this side has to clear. On a book that's the vig-inclusive
	 *  implied probability of a quoted price; on a pick'em board it's the
	 *  break-even a slip needs, which is an assumption — see
	 *  `PropBoard.pricing_note`. */
	implied_pct: number;
	edge_pct: number;
	has_edge: boolean;
	kelly_pct: number | null;
}

/** One prop, both sides, as a card. */
export interface PropCard {
	game_id: string;
	away: string;
	home: string;
	matchup: string;
	first_pitch: string | null;
	is_live: boolean;
	player: string;
	team: string | null;
	stat: string;
	side: 'batter' | 'pitcher';
	line: number;
	n_sims: number;
	over: PropSide | null;
	under: PropSide | null;
	/** Which side our model prefers *at the posted price*, or null. Edge, not
	 *  probability — a 70% shot priced at 75% is not a bet. */
	best: 'over' | 'under' | null;
	top_edge: number;
}

export interface PropGroup {
	side: 'batter' | 'pitcher';
	stat: string;
	label: string;
	cards: PropCard[];
	count: number;
	with_edge: number;
	/** How many the source quoted for this stat, and how many were on players
	 *  no lineup we simulated contains. One card out of sixteen offered is a
	 *  different fact from a stat the book only posted once. */
	offered?: number;
	unmatched?: number;
}

/** One game on the filter strip. Built from the cards, so a game listed
 *  here always has props behind it. */
export interface PropBoardGame {
	game_id: string;
	away: string;
	home: string;
	matchup: string;
	first_pitch: string | null;
	is_live: boolean;
	cards: number;
	with_edge: number;
}

export interface PropBoard {
	date: string;
	generated_at: string;
	ready: boolean;
	/** Which feed built this board. PrizePicks is the only prop source, so this
	 *  is always "PrizePicks" — carried anyway so a page never has to assume. */
	book?: string;
	/** Set only when the source posts no odds. Says where the "needs"
	 *  percentages came from instead, so a break-even we chose can't be read as
	 *  a price somebody quoted. */
	pricing_note?: string;
	games: PropBoardGame[];
	/** {"<game_id>|<side>/<stat>": how many the source's public feed quoted}.
	 *  Per game, because board-wide coverage is misleading the moment the game
	 *  filter is on — and that filter is how you compare against the app. */
	coverage?: Record<string, number>;
	groups: PropGroup[];
	totals: { cards: number; players: number; with_edge: number };
	games_considered?: number;
	games_priced?: number;
	props_available?: boolean;
	live_games?: number;
	unmapped_stats?: string[];
	/** Where props went that never became a card. Three causes with identical
	 *  symptoms: the feed never sent it, we couldn't map the market, or the
	 *  player isn't in a lineup we simulated. */
	source?: {
		/** What the feed quoted, before any of our filtering. */
		quoted: number;
		/** What survived the market mapping. */
		offered: number;
		priced: number;
		unmatched_player: number;
		dropped: Record<string, number>;
		/** What their public feed carries per market, slate-wide. */
		by_stat?: Record<string, number>;
	};
	notes?: string[];
	slate?: SlateStatus;
}

/** How long a plate appearance runs, and what it ends in. */
export interface AtBatForecast {
	batter: string;
	pitcher: string;
	batter_hand: string;
	pitcher_hand: string;

	/** The headline: the mean, and the whole number a reader carries away. */
	expected_pitches: number;
	likely_pitches: number;
	/** The scale around it — three numbers summing to 100. An at-bat that
	 *  averages four pitches is very rarely four pitches, and an expectation
	 *  with no spread is the kind of number that looks authoritative and says
	 *  nothing. */
	more_pct: number;
	same_pct: number;
	fewer_pct: number;
	/** P(the at-bat ends on exactly n more pitches). `plus` marks the last
	 *  bucket when the long tail has been folded into it. */
	distribution: { n: number; pct: number; plus?: boolean }[];

	/** Fitted to the Log5 matchup distribution, not modelled separately — so
	 *  these are the same numbers the matchup card shows, by construction. */
	strikeout_pct: number;
	walk_pct: number;
	in_play_pct: number;
	hit_by_pitch_pct: number;
	/** The count this forecast starts from — the live one when somebody is
	 *  batting, "0-0" between innings. */
	start_count: string;
	/** What the same matchup looked like at 0-0, present only once the at-bat
	 *  is under way. The contrast is the point: showing only the current
	 *  number hides how much the count has already done. */
	started_expected_pitches: number | null;
	started_strikeout_pct: number | null;
	started_walk_pct: number | null;
	started_in_play_pct: number | null;
	fit_capped: boolean;
	fit_error: number;
	notes: string[];
}

/** One pitching staff's countdown to the last out. */
export interface TeamPitches {
	team: string;
	side: 'home' | 'away';
	/** The staff currently on the mound — the one whose number is ticking. */
	is_pitching: boolean;
	outs_remaining: number;
	expected_remaining: number;
	/** A nine-inning staff's whole-game figure (~146), so the countdown has a
	 *  scale to be read against rather than being a bare number. */
	expected_total: number;
	pct_remaining: number;
	/** Actual pitches thrown, from the box score. Null when it couldn't be
	 *  read — the countdown is estimated off the innings, so a missing box
	 *  score costs the over-run and nothing else. */
	thrown: number | null;
	/** Outs this staff has already recorded — the denominator behind `pace`. */
	outs_recorded: number;
	/** Their own pitches per out tonight, shrunk towards the league's 5.41. A
	 *  staff reading 6.8 is having a long night, and the projection follows it
	 *  rather than insisting on the average. */
	pace: number;
	/** Thrown plus expected remaining: where this staff's night actually lands,
	 *  as opposed to where a league-average one would. */
	projected_total: number | null;
	/** How far past the whole-game estimate they already are. A staff that
	 *  walks the park blows through 146 well before the ninth, and counting
	 *  down towards zero there describes a game that isn't happening. */
	over_estimate: number;
	/** No outs left to record. Distinct from an over-run: a home staff is
	 *  legitimately finished the moment the top of the ninth ends. */
	complete: boolean;
}

export interface NextAtBat {
	game_id: string;
	available: boolean;
	/** "at_plate" — the hitter in the box, forecast from the count he's in.
	 *  "on_deck" — between innings, so the next hitter up from 0-0. */
	subject: string;
	batter: string;
	pitcher: string;
	batter_team: string | null;
	inning: number | null;
	is_top_inning: boolean | null;
	outs: number | null;
	/** The count the forecast starts from. */
	balls: number;
	strikes: number;
	on_deck: string | null;
	in_hole: string | null;
	current_batter: string | null;
	/** "season" when the forecast is built on that player's own line, "league"
	 *  when we hold none and a baseline is standing in. About a fifth of lineup
	 *  slots on a night are the latter, so the page marks the number itself
	 *  rather than relying on the note beneath it being read. */
	batter_profile: string;
	pitcher_profile: string;
	forecast: AtBatForecast | null;
	/** Both staffs' countdowns. Present whenever the game is under way, even
	 *  when no forecast could be built — the countdown needs only the inning,
	 *  so an unknown reliever shouldn't cost you it. */
	team_pitches: TeamPitches[];
	/** True past the ninth, where the remaining length is unknowable and the
	 *  countdown covers only the halves that must still be played. */
	extra_innings: boolean;
	/** Why there's nothing to show. "The game hasn't started", "the feed is
	 *  unreachable" and "we don't have this reliever" are three different facts
	 *  that an empty panel would render identically. */
	reason: string;
	notes: string[];
}

/** One NFL prop, exactly as PrizePicks posted it.
 *
 *  Deliberately unmapped: there's no NFL simulator to translate these onto, so
 *  `market` is PrizePicks' own stat_type and `market_label` is the same string
 *  as they wrote it. Nothing is dropped for failing to match a vocabulary.
 *
 *  No prices, and that's not an omission — PrizePicks posts none, because the
 *  payout is on the slip rather than the pick. */
export interface NFLProp {
	player_name: string;
	player_key: string;
	market: string;
	market_label: string;
	line: number;
	team: string | null;
	position: string | null;
	opponent: string | null;
	/** "standard" | "demon" | "goblin". Demons take a harder line for a bigger
	 *  share of the slip, goblins an easier one for less. Shown rather than
	 *  dropped: this page is a browser, not a bet. */
	odds_type: string;
	is_promo: boolean;
	game_status: string;
	is_live: boolean;
}

export interface NFLPropSearch {
	query: string;
	count: number;
	players: number;
	props: NFLProp[];
	/** True when the empty result is PrizePicks being unreachable rather than
	 *  the player genuinely having no line. Opposite meanings, same empty list. */
	unreachable?: boolean;
	note?: string | null;
}

/** One window of graded games, measured against itself. */
export interface OutlookWindow {
	start: string;
	end: string;
	days: number;
	games: number;
	winner_pct: number | null;
	winner_n: number;
	/** Signed average miss on the game total: positive means real games
	 *  outscored us. Signed, because the *direction* is the only part that
	 *  points at a bet — the size just says how noisy we are. */
	total_bias: number | null;
	total_mae: number | null;
	total_n: number;
	/** How often the real total landed inside p10–p90. Targets 80%. */
	coverage_pct: number | null;
	coverage_n: number;
	/** Share of games priced 45–55% — how often we have no real opinion. */
	flat_pct: number | null;
	flat_n: number;
	calibration_gap: number | null;
}

/** A measured finding, with both of its tests reported rather than hidden.
 *
 *  `usable` is the only one that produces an outlook line: it needs the gap to
 *  survive the whole record (`persistent`) *and* to be bigger than the noise of
 *  a sample that size (`significant`). The failures are kept because having
 *  looked and found nothing is itself worth showing. */
export interface OutlookSignal {
	key: string;
	headline: string;
	detail: string;
	lifetime: number | null;
	recent: number | null;
	expected: number;
	gap: number | null;
	n: number;
	direction: string;
	significant: boolean;
	persistent: boolean;
	usable: boolean;
}

export interface Outlook {
	generated_at: string;
	windows: { latest: OutlookWindow; recent: OutlookWindow; lifetime: OutlookWindow };
	signals: OutlookSignal[];
	outlook: { where: string; detail: string; confidence: 'firm' | 'tentative' }[];
	verdict: string;
	caveats: string[];
	method: string;
}

export interface AccuracyReport {
	window: { start: string; end: string; games: number; pregame_games: number; resimulated_games: number };
	generated_at: string;
	outcomes: {
		games_scored: number;
		ties: number;
		winner_accuracy_pct: number | null;
		winners_correct: number;
		brier: number | null;
		log_loss: number | null;
		run_mae: number | null;
		total_mae: number | null;
		spread_mae: number | null;
		total_coverage_pct: number | null;
		team_runs_coverage_pct: number | null;
		total_centrality_pct: number | null;
		spread_centrality_pct: number | null;
		mean_exact_score_pct: number | null;
		calibration: CalibrationBucket[];
	};
	batting: StatBlock;
	pitching: StatBlock;
	by_position: PositionAccuracy[];
	by_lineup_slot: { slot: number; stats: StatBlock }[];
	players: PlayerAccuracy[];
	games: ScoredGameSummary[];
	coverage: { unprojected_appearances: number; projected_but_absent: number };
	refreshed?: Record<string, number | string> | null;
}

export interface ScoredStat {
	projected: number | null;
	actual: number | null;
	error?: number;
}

export interface ScoredPlayer {
	player_id: number;
	name: string;
	team: string;
	side: 'batter' | 'pitcher';
	position: string | null;
	role?: string;
	lineup_slot: number | null;
	projected: boolean;
	played: boolean;
	aggregate?: boolean;
	arms_used?: number;
	starter_changed?: boolean;
	stats: Record<string, ScoredStat>;
}

export interface ScoredGame {
	game_id: string;
	date: string;
	home: string;
	away: string;
	n: number;
	pregame: boolean;
	actual: { home_runs: number; away_runs: number; total: number; spread: number; winner: string; status: string | null };
	outcome: Record<string, any>;
	batters: ScoredPlayer[];
	pitchers: ScoredPlayer[];
	has_boxscore: boolean;
	scored_at: string;
}

/** What baseball has actually been doing over the last few days. */
export interface RecentTrend {
	metric: string;
	label: string;
	level: number;
	display: string;
	comparison: number | null;
	comparison_display: string | null;
	change: number | null;
	change_display: string | null;
	change_pct: number | null;
	z: number | null;
	/** Clear of week-to-week wobble; `firm` is the stronger of the two tiers. */
	moving: boolean;
	firm: boolean;
	direction: 'up' | 'down' | 'flat';
	games: number;
	days: number;
	/** `season_to_date` measures the league's week against seasons of league
	 *  games and is the strongest; `prior_games` compares our own record with
	 *  itself; `season_form` leans on projections and is the weakest. */
	basis: 'season_to_date' | 'prior_games' | 'season_form' | 'level_only';
	headline: string;
	detail: string;
}

/** A forecast with a window on it, so it can be marked rather than remembered.
 *  `kind: 'league'` is about baseball; `kind: 'model'` is about the
 *  simulation's own error and stays off the front page. */
export interface ExpectedTrend {
	id: string;
	kind?: 'league' | 'model';
	issued: string;
	horizon: 'this_week' | 'next_week';
	window_start: string;
	window_end: string;
	metric: string;
	label?: string;
	headline: string;
	detail?: string;
	predicted: number;
	lo: number;
	hi: number;
	null: number;
	ratio?: number | null;
	z?: number;
	n_basis: number;
	confidence: 'high' | 'medium' | 'low';
	basis?: string;
	graded: boolean;
	/** League forecasts carry pre-formatted numbers so the page never has to
	 *  guess whether a metric is a count or a percentage. */
	predicted_display?: string;
	range_display?: string;
	now_display?: string;
	baseline_display?: string;
	/** How much of the current swing is expected to survive the week. */
	carry_pct?: number;
	/** Which record the forecast rests on. */
	source?: 'league_history' | 'graded_record';
	/** How this calendar week has historically compared with its own season,
	 *  as a percentage. Zero when prior seasons disagree on the pattern. */
	calendar_pct?: number;
	calendar_seasons?: number[];
	season_base?: number;
	n_weeks?: number;
	/** Which record the grading was done against, once graded. */
	graded_against?: 'league_history' | 'graded_record';
	/** Computed on the fly because the record held nothing to show. */
	provisional?: boolean;
	/** Present once the window has played out. */
	actual?: number;
	actual_display?: string;
	hit?: boolean;
	direction_right?: boolean;
	n_window?: number;
}

export interface TrendScoreBlock {
	n: number;
	hit_rate?: number;
	direction_rate?: number;
}

export interface TrendsReport {
	generated_at: string;
	record_games: number;
	this_week: RecentTrend[];
	next_week: ExpectedTrend[];
	/** Seasons of league-wide games behind the baselines and the calendar. */
	history: { seasons: number[]; games: number };
	recent_graded: ExpectedTrend[];
	model_watch: ExpectedTrend[];
	scorecard: {
		issued: number;
		graded: number;
		open: number;
		overall: TrendScoreBlock;
		by_horizon: Record<string, TrendScoreBlock>;
		by_confidence: Record<string, TrendScoreBlock>;
		by_kind: Record<string, TrendScoreBlock>;
		target_hit_rate: number;
	};
	drift: {
		games: number;
		actionable: string[];
		metrics: {
			metric: string;
			n: number;
			mean: number;
			z: number;
			ratio?: number;
			verdict: string;
			more_games_needed?: number;
		}[];
	};
}

/** How far the server has got simulating a slate. Everything on the page reads
 *  those runs, so this is the one progress bar that matters. */
export interface SlateStatus {
	date: string;
	/** idle — nobody has opened this slate yet; running; ready — every game
	 *  simulated; partial — finished with games missing after retries;
	 *  cancelled — superseded by a re-run already under way. */
	state: 'idle' | 'running' | 'ready' | 'partial' | 'cancelled';
	total: number;
	done: number;
	/** Games the simulation couldn't run after every retry. */
	failed: string[];
	/** {game_id: last error}. Without this a failure told nobody anything. */
	reasons: Record<string, string>;
	/** Lineup sides MLB has actually posted, out of `lineup_slots` (two a game).
	 *  A projection and a confirmed card are different claims. */
	confirmed: number;
	lineup_slots: number;
	/** The server is still checking for lineups being posted. */
	watching: boolean;
	/** Games re-simulated because their lineup changed. Bumps when a card is
	 *  posted, which is the page's cue to re-read the cards. */
	resimulated: number;
	/** How many passes it took. More than one means games were retried. */
	attempts: number;
	/** Every game on the slate has a simulation behind it. */
	complete: boolean;
	/** Still working. Everything downstream waits on this being false. */
	running: boolean;
	elapsed_seconds: number;
}

export interface ChatStatus {
	available: boolean;
	model: string | null;
	/** A key is set but isn't shaped like an Anthropic one — a shape check, not
	 *  a validity check, so a false here doesn't mean the key works. */
	key_suspect?: boolean;
}

/** One turn of conversation. The client holds the history and resends it —
 *  the server keeps no session, so a reload starts clean. */
export interface ChatMessage {
	role: 'user' | 'assistant';
	content: string;
}

/** A server event: `text` is a chunk of the reply, `tool` names a lookup that
 *  just started, `done` ends the turn, `error` reports a failure mid-stream. */
export type ChatEvent =
	| { type: 'text'; text: string }
	| { type: 'tool'; name: string }
	| { type: 'done' }
	| { type: 'error'; message: string };

export interface BettingEdge {
	game_id: string;
	market: string;
	model_probability: number;
	implied_probability: number;
	edge: number;
	kelly_fraction: number;
	recommended_stake_pct: number;
	expected_value: number;
	confidence_interval_95: [number, number];
}

export interface BatterRow {
	player_id: number;
	name: string;
	season: number;
	team: string;
	hand: string;
	pa: number;
	woba: number;
	xwoba: number;
	iso: number;
	babip: number;
	hr_rate: number;
	k_rate: number;
	bb_rate: number;
	single_rate: number;
	double_rate: number;
	triple_rate: number;
	hbp_rate: number;
	ipo_rate: number;
	platoon_split: Record<string, number>;
	sprint_speed_ft_s: number | null;
}

export interface PitcherRow {
	player_id: number;
	name: string;
	season: number;
	team: string;
	hand: string;
	role: string;
	bf: number;
	fip: number;
	hr_allowed: number;
	k_rate: number;
	bb_allowed: number;
	single_allowed: number;
	double_allowed: number;
	triple_allowed: number;
	hbp_allowed: number;
	ipo_rate: number;
	platoon_split: Record<string, number>;
}

export interface PlayerDetail {
	player_id: number;
	name: string;
	batting: BatterRow[];
	pitching: PitcherRow[];
}

export interface GameLogEntry {
	date: string;
	opponent: string;
	is_home: boolean;
	game_pk: number | null;
	status: 'Final' | 'Live' | 'Preview' | string;
	inning: number | null;
	inning_half: 'Top' | 'Bottom' | string | null;
	stats: Record<string, number | string | null>;
}

export interface PlayerGameLog {
	player_id: number;
	season: number;
	group: 'hitting' | 'pitching';
	games: GameLogEntry[];
}

export interface TeamAggregate {
	team: string;
	lineup_woba: number;
	lineup_xwoba: number;
	lineup_iso: number;
	lineup_k_rate: number;
	lineup_bb_rate: number;
	lineup_hr_rate: number;
	sprint_speed: number | null;
	bullpen_fip: number | null;
	bullpen_k_rate: number | null;
	park_runs_factor: number | null;
	roster?: BatterRow[];
	[key: string]: unknown;
}

export interface SimulateOptions {
	game_id: string;
	n: number;
	seed?: number | null;
	season?: number;
	shrink_pa?: number;
	shrink_bf?: number;
	use_bullpen?: boolean;
	use_context?: boolean;
	calibrate?: boolean;
	calibrate_totals?: boolean;
	// Set both to run a true Monte Carlo conditioned on this exact final score.
	target_away?: number;
	target_home?: number;
	// Per-batter what-if rate multipliers: { [playerId]: { hits?, home_runs?, bb?, k? } }.
	rate_overrides?: Record<string, Record<string, number>>;
	// Per-pitcher what-if rate multipliers: { [pitcherId]: { hits_allowed?,
	// hr_allowed?, bb_allowed?, k? } }.
	pitcher_overrides?: Record<string, Record<string, number>>;
}

// Force a fresh network round-trip for live-polled endpoints (score/linescore/
// boxscore). iOS Safari (and some proxies) will otherwise serve a cached copy
// of a repeated GET URL, so a 20s poll of the same URL returns stale data even
// though the server has newer numbers. A unique query param makes every request
// URL distinct (defeats shared/proxy caches too), and cache:'no-store' tells
// the browser not to read or write its own cache.
function live<T>(url: string, timeoutMs?: number): Promise<T> {
	const busted = url + (url.includes('?') ? '&' : '?') + `_=${Date.now()}`;
	return jsonFetch<T>(busted, { cache: 'no-store' }, timeoutMs);
}

async function jsonFetch<T>(input: string, init?: RequestInit, timeoutMs = 15_000): Promise<T> {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	let res: Response;
	try {
		// `no-store` on every API call: these are all dynamic, and a live line
		// served from the browser's heuristic cache is a price that no longer
		// exists. The server sends the matching directive; this is the other
		// half, since a cached response can be reused before the request is
		// ever made.
		res = await fetch(input, { cache: 'no-store', ...init, signal: controller.signal });
	} catch (e) {
		if (controller.signal.aborted) throw new Error(`timed out after ${timeoutMs}ms: ${input}`);
		throw e;
	} finally {
		clearTimeout(timer);
	}
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const body = await res.json();
			detail = body.detail ?? detail;
		} catch {
			/* non-JSON error body */
		}
		throw new Error(`${res.status}: ${detail}`);
	}
	return res.json() as Promise<T>;
}

export const api = {
	dates: () => jsonFetch<string[]>('/api/dates'),

	// The live MLB schedule call can be slow on a restricted network — cap it
	// well under the backend's own budget so the UI can fall back promptly.
	// no-cache: this is polled for live scores, must never be served stale.
	upcoming: (days = 3) => live<GameSchedule[]>(`/api/upcoming?days=${days}`, 12_000),

	games: (date: string) =>
		jsonFetch<GameSchedule[]>(`/api/games?date=${encodeURIComponent(date)}`),

	// Re-fetch a date's schedule from MLB (picks up reschedules / new
	// doubleheaders), then returns it. Best-effort; capped so a slow MLB call
	// can't hang the slate. No-cache so a repeat visit always re-checks.
	gamesLive: (date: string) =>
		live<GameSchedule[]>(`/api/games-live?date=${encodeURIComponent(date)}`, 12_000),

	simulate: (body: SimulateOptions) =>
		jsonFetch<SimResult>(
			'/api/simulate',
			{
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify(body)
			},
			// Two reasons this is generous. A conditioned run rejection-samples
			// up to ~10k games. And a plain run can now queue behind the
			// server's slate warm-up — waiting for that is the point, but at
			// the old 15s ceiling the wait was being reported to the user as a
			// failed load.
			body.target_away != null ? 60_000 : 90_000
		),

	bet: (body: {
		game_id: string;
		odds: { home_ml: number; away_ml: number; total_line: number; over_ml: number; under_ml: number };
		kelly_fraction: number;
		n: number;
		seed?: number | null;
	}) =>
		jsonFetch<BettingEdge[]>('/api/bet', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body)
		}),

	players: (kind: 'batters' | 'pitchers', season?: number) =>
		jsonFetch<(BatterRow | PitcherRow)[]>(
			`/api/players?kind=${kind}${season ? `&season=${season}` : ''}`
		),

	player: (id: number) => jsonFetch<PlayerDetail>(`/api/player/${id}`),

	playerGameLog: (id: number, group: 'hitting' | 'pitching', season?: number) =>
		jsonFetch<PlayerGameLog>(
			`/api/player/${id}/gamelog?group=${group}${season ? `&season=${season}` : ''}`
		),

	teams: () => jsonFetch<string[]>('/api/teams'),

	team: (abbr: string) => jsonFetch<TeamAggregate>(`/api/team/${encodeURIComponent(abbr)}`),

	teamstats: () => jsonFetch<TeamAggregate[]>('/api/teamstats'),

	// Ranked plays for a slate. Server-side this simulates every game, so it
	// is cached for three hours; a warm cache returns instantly.
	// `refresh` discards the cached simulations for the slate and re-runs them,
	// so a manual re-run reflects confirmed lineups and live game state rather
	// than replaying whatever was simulated earlier.
	bestBets: (date?: string, refresh = false) => {
		const q = new URLSearchParams();
		if (date) q.set('date', date);
		if (refresh) q.set('refresh', 'true');
		const qs = q.toString();
		return jsonFetch<BestBetsReport>(
			`/api/best-bets${qs ? `?${qs}` : ''}`,
			undefined,
			120_000
		);
	},

	// Live-polled → never cached (see `live`): odds move during the game.
	// Post-game accuracy (sim vs. actual). Runs two sims server-side, so give it
	// room. Returns { final: false } for a game that hasn't finished.
	accuracy: (gameId: string) =>
		jsonFetch<GameAccuracy>(`/api/game/${encodeURIComponent(gameId)}/accuracy`, undefined, 45_000),

	// Simulate the remainder of an in-progress game from its live state.
	// Never cached (the state moves every pitch) and given room for the sim.
	liveSim: (gameId: string, n = 3000) =>
		live<LiveSim>(`/api/game/${encodeURIComponent(gameId)}/live-sim?n=${n}`, 45_000),

	// Live-refreshed schedule entry (score/inning/status as of now) for one game.
	game: (gameId: string) => live<GameSchedule>(`/api/game/${encodeURIComponent(gameId)}`),

	linescore: (gameId: string) =>
		live<GameLinescore>(`/api/game/${encodeURIComponent(gameId)}/linescore`),

	// Pitch-by-pitch forecast for the at-bat that hasn't started yet. Never
	// cached: the on-deck hitter changes every time somebody makes an out.
	nextAtBat: (gameId: string) =>
		live<NextAtBat>(`/api/game/${encodeURIComponent(gameId)}/next-at-bat`),

	boxscore: (gameId: string) => live<GameBoxscore>(`/api/game/${encodeURIComponent(gameId)}/boxscore`),

	// Rolling accuracy over a window of finished games. Served from stored
	// per-game scorecards, so the default read is an aggregation and returns
	// quickly. `refresh` grades any finished game not yet graded — that costs a
	// simulation per game, hence the long ceiling.
	accuracyReport: (opts: { date?: string; days?: number; refresh?: boolean } = {}) => {
		const q = new URLSearchParams();
		if (opts.date) q.set('date', opts.date);
		if (opts.days) q.set('days', String(opts.days));
		if (opts.refresh) q.set('refresh', 'true');
		const qs = q.toString();
		return jsonFetch<AccuracyReport>(
			`/api/accuracy/report${qs ? `?${qs}` : ''}`,
			undefined,
			opts.refresh ? 300_000 : 30_000
		);
	},

	// The forward-looking read: where our own record says our numbers have
	// been unreliable. Aggregated from stored scorecards, so it's cheap.
	outlook: () => jsonFetch<Outlook>('/api/outlook', undefined, 300_000),

	// Every priced MLB prop, both sides, grouped by stat. Same pricing as the
	// ranked panel — this one just doesn't filter.
	propBoard: (opts: { date?: string } = {}) => {
		const q = opts.date ? `?date=${encodeURIComponent(opts.date)}` : '';
		return jsonFetch<PropBoard>(`/api/props/board${q}`, undefined, 60_000);
	},

	// PrizePicks' NFL props by player name. Cached briefly server-side, so
	// typing doesn't turn into one upstream call per keystroke.
	nflProps: (q: string) =>
		jsonFetch<NFLPropSearch>(`/api/nfl/props?q=${encodeURIComponent(q)}`, undefined, 30_000),

	// One game's full scorecard: every player, projected against actual.
	accuracyGame: (gameId: string) =>
		jsonFetch<ScoredGame>(`/api/accuracy/game/${encodeURIComponent(gameId)}`, undefined, 60_000),

	// What the model is expected to get wrong this week and next, plus how
	// well those expectations have held. Read-only — the forecasts themselves
	// are issued and graded by the scheduled job.
	trends: () => jsonFetch<TrendsReport>('/api/trends', undefined, 30_000),

	// Whether the assistant is configured on this deployment. Asked before the
	// panel renders, so an unconfigured Space shows no chat rather than a box
	// that fails when you type in it.
	chatStatus: () => jsonFetch<ChatStatus>('/api/chat/status', undefined, 10_000),

	// Polled while the slate warms. Never cached — the whole value is that the
	// number moves.
	slateStatus: (date: string) =>
		live<SlateStatus>(`/api/slate/status?date=${encodeURIComponent(date)}`, 10_000),

	// Discard the server's runs for a slate and start again. Returns as soon as
	// the new warm-up is under way — poll `slateStatus` for the rest.
	slateRerun: (date: string) =>
		jsonFetch<SlateStatus & { dropped: number }>(
			`/api/slate/rerun?date=${encodeURIComponent(date)}`,
			{ method: 'POST' },
			30_000
		),

	/**
	 * Ask the assistant, streaming the reply back a chunk at a time.
	 *
	 * Not `jsonFetch` — the response is an event stream, and the whole point is
	 * to render it as it arrives. `onEvent` is called for every server event;
	 * the returned promise settles when the stream closes.
	 */
	chat: async (
		messages: ChatMessage[],
		onEvent: (e: ChatEvent) => void,
		signal?: AbortSignal
	): Promise<void> => {
		const res = await fetch('/api/chat', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ messages }),
			signal
		});
		if (!res.ok || !res.body) {
			let detail = `chat failed (${res.status})`;
			try {
				const body = await res.json();
				if (body?.detail) detail = body.detail;
			} catch {
				// A non-JSON error body is not worth a second failure.
			}
			throw new Error(detail);
		}
		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buffer = '';
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			// SSE frames are separated by a blank line. A chunk can split one in
			// half, so anything after the last separator stays in the buffer.
			const frames = buffer.split('\n\n');
			buffer = frames.pop() ?? '';
			for (const frame of frames) {
				const line = frame.split('\n').find((l) => l.startsWith('data:'));
				if (!line) continue;
				try {
					onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent);
				} catch {
					// One malformed frame costs a chunk, not the conversation.
				}
			}
		}
	}
};
