// Static MLB team metadata (names + home venues) for UI display.

export interface TeamMeta {
	name: string;
	venue: string;
}

export const TEAM_META: Record<string, TeamMeta> = {
	ATH: { name: 'Athletics', venue: 'Sutter Health Park' },
	ATL: { name: 'Atlanta Braves', venue: 'Truist Park' },
	AZ: { name: 'Arizona Diamondbacks', venue: 'Chase Field' },
	BAL: { name: 'Baltimore Orioles', venue: 'Oriole Park at Camden Yards' },
	BOS: { name: 'Boston Red Sox', venue: 'Fenway Park' },
	CHC: { name: 'Chicago Cubs', venue: 'Wrigley Field' },
	CIN: { name: 'Cincinnati Reds', venue: 'Great American Ball Park' },
	CLE: { name: 'Cleveland Guardians', venue: 'Progressive Field' },
	COL: { name: 'Colorado Rockies', venue: 'Coors Field' },
	CWS: { name: 'Chicago White Sox', venue: 'Rate Field' },
	DET: { name: 'Detroit Tigers', venue: 'Comerica Park' },
	HOU: { name: 'Houston Astros', venue: 'Daikin Park' },
	KC: { name: 'Kansas City Royals', venue: 'Kauffman Stadium' },
	LAA: { name: 'Los Angeles Angels', venue: 'Angel Stadium' },
	LAD: { name: 'Los Angeles Dodgers', venue: 'Dodger Stadium' },
	MIA: { name: 'Miami Marlins', venue: 'loanDepot park' },
	MIL: { name: 'Milwaukee Brewers', venue: 'American Family Field' },
	MIN: { name: 'Minnesota Twins', venue: 'Target Field' },
	NYM: { name: 'New York Mets', venue: 'Citi Field' },
	NYY: { name: 'New York Yankees', venue: 'Yankee Stadium' },
	PHI: { name: 'Philadelphia Phillies', venue: 'Citizens Bank Park' },
	PIT: { name: 'Pittsburgh Pirates', venue: 'PNC Park' },
	SD: { name: 'San Diego Padres', venue: 'Petco Park' },
	SEA: { name: 'Seattle Mariners', venue: 'T-Mobile Park' },
	SF: { name: 'San Francisco Giants', venue: 'Oracle Park' },
	STL: { name: 'St. Louis Cardinals', venue: 'Busch Stadium' },
	TB: { name: 'Tampa Bay Rays', venue: 'George M. Steinbrenner Field' },
	TEX: { name: 'Texas Rangers', venue: 'Globe Life Field' },
	TOR: { name: 'Toronto Blue Jays', venue: 'Rogers Centre' },
	WSH: { name: 'Washington Nationals', venue: 'Nationals Park' }
};

export function teamName(abbr: string): string {
	return TEAM_META[abbr]?.name ?? abbr;
}

export function teamVenue(abbr: string): string {
	return TEAM_META[abbr]?.venue ?? '—';
}
