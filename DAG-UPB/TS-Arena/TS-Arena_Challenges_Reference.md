# TS-Arena Challenges: Technical Reference

Reference for the TS-Arena forecasting challenges. Each challenge is documented in its own section with its challenge ID, frequency, horizon and context length, a short description of what it forecasts, and the full list of time series it contains (with series IDs).

## SMARD: German & European electricity market (Bundesnetzagentur)

### Challenge 1. SMARD Day-Ahead Market Price Challenge: 24h horizon, 15-min frequency

**Challenge ID:** 1

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast the day-ahead wholesale electricity price (€/MWh), the price set in the previous day's auction for each delivery period. The series cover the German-Luxembourg (DE-LU) bidding zone and the neighbouring European bidding zones that SMARD publishes.

**Companion challenge:** ID 4 (same series at 72h horizon, 1h frequency).

**Series (15)**

- `[68]` **DE-LU**: Germany/Luxembourg core bidding-zone price
- `[66]` **DE-LU neighbors**: aggregate price of zones bordering DE-LU
- `[57]` **AT**: Austria bidding-zone price
- `[58]` **BE**: Belgium bidding-zone price
- `[59]` **CH**: Switzerland bidding-zone price
- `[60]` **CZ**: Czech Republic bidding-zone price
- `[67]` **DK1**: Denmark West (DK1) price
- `[70]` **DK2**: Denmark East (DK2) price
- `[69]` **FR**: France bidding-zone price
- `[76]` **HU**: Hungary bidding-zone price
- `[77]` **IT-North**: Northern Italy bidding-zone price
- `[78]` **NL**: Netherlands bidding-zone price
- `[79]` **NO2**: Southern Norway (NO2) price
- `[80]` **PL**: Poland bidding-zone price
- `[86]` **SI**: Slovenia bidding-zone price

### Challenge 4. SMARD Day-Ahead Market Price Challenge: 72h horizon, 1h frequency

**Challenge ID:** 4

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast the day-ahead wholesale electricity price (€/MWh), the price set in the previous day's auction for each delivery period. The series cover the German-Luxembourg (DE-LU) bidding zone and the neighbouring European bidding zones that SMARD publishes.

**Companion challenge:** ID 1 (same series at 24h horizon, 15-min frequency).

**Series (15)**

- `[68]` **DE-LU**: Germany/Luxembourg core bidding-zone price
- `[66]` **DE-LU neighbors**: aggregate price of zones bordering DE-LU
- `[57]` **AT**: Austria bidding-zone price
- `[58]` **BE**: Belgium bidding-zone price
- `[59]` **CH**: Switzerland bidding-zone price
- `[60]` **CZ**: Czech Republic bidding-zone price
- `[67]` **DK1**: Denmark West (DK1) price
- `[70]` **DK2**: Denmark East (DK2) price
- `[69]` **FR**: France bidding-zone price
- `[76]` **HU**: Hungary bidding-zone price
- `[77]` **IT-North**: Northern Italy bidding-zone price
- `[78]` **NL**: Netherlands bidding-zone price
- `[79]` **NO2**: Southern Norway (NO2) price
- `[80]` **PL**: Poland bidding-zone price
- `[86]` **SI**: Slovenia bidding-zone price

### Challenge 2. SMARD Net Load Challenge: 24h horizon, 15-min frequency

**Challenge ID:** 2

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast total grid load (Netzlast), the electricity demand drawn from the transmission grid, in MW. Despite the "Net Load" name, the series are SMARD's total grid-load figures broken down by transmission control area and country aggregate, not residual (demand-minus-renewables) load.

**Companion challenge:** ID 5 (same series at 72h horizon, 1h frequency).

**Series (10)**

- `[109]` **50Hertz**: grid load in the 50Hertz zone (north-east Germany)
- `[111]` **Amprion**: grid load in the Amprion zone (western Germany)
- `[114]` **TenneT**: grid load in the TenneT DE zone (north-south corridor)
- `[113]` **TransnetBW**: grid load in the TransnetBW zone (south-west Germany)
- `[106]` **DE**: total German grid load
- `[107]` **DE-LU**: combined Germany-Luxembourg grid load
- `[105]` **AT**: total Austrian grid load
- `[110]` **APG**: grid load in Austria's APG control area
- `[108]` **LU**: total Luxembourg grid load
- `[112]` **Creos**: grid load in Luxembourg's Creos network

### Challenge 5. SMARD Net Load Challenge: 72h horizon, 1h frequency

**Challenge ID:** 5

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast total grid load (Netzlast), the electricity demand drawn from the transmission grid, in MW. Despite the "Net Load" name, the series are SMARD's total grid-load figures broken down by transmission control area and country aggregate, not residual (demand-minus-renewables) load.

**Companion challenge:** ID 2 (same series at 24h horizon, 15-min frequency).

**Series (10)**

- `[109]` **50Hertz**: grid load in the 50Hertz zone (north-east Germany)
- `[111]` **Amprion**: grid load in the Amprion zone (western Germany)
- `[114]` **TenneT**: grid load in the TenneT DE zone (north-south corridor)
- `[113]` **TransnetBW**: grid load in the TransnetBW zone (south-west Germany)
- `[106]` **DE**: total German grid load
- `[107]` **DE-LU**: combined Germany-Luxembourg grid load
- `[105]` **AT**: total Austrian grid load
- `[110]` **APG**: grid load in Austria's APG control area
- `[108]` **LU**: total Luxembourg grid load
- `[112]` **Creos**: grid load in Luxembourg's Creos network

### Challenge 3. SMARD Generation Challenge (all generation types): 24h horizon, 15-min frequency

**Challenge ID:** 3

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast electricity generation (MW) broken down by energy source and transmission control area. A representative round carried 16 series covering lignite, photovoltaics (solar), offshore wind and onshore wind across the German, Austrian and Luxembourg control areas. The full catalogue for this challenge can reach roughly two dozen source-by-area series and varies between rounds.

**Companion challenge:** ID 6 (same series at 72h horizon, 1h frequency).

**Series (16)**

- `[18]` **Lignite (50Hertz)**: brown-coal (lignite) output, 50Hertz zone
- `[19]` **Lignite (Amprion)**: brown-coal (lignite) output, Amprion zone
- `[138]` **Photovoltaic (50Hertz)**: solar PV output, 50Hertz zone
- `[139]` **Photovoltaic (APG)**: solar PV output, Austria (APG)
- `[140]` **Photovoltaic (Amprion)**: solar PV output, Amprion zone
- `[137]` **Photovoltaic (Creos)**: solar PV output, Luxembourg (Creos)
- `[141]` **Photovoltaic (TenneT)**: solar PV output, TenneT zone
- `[142]` **Photovoltaic (TransnetBW)**: solar PV output, TransnetBW zone
- `[171]` **Wind Offshore (50Hertz)**: offshore wind output, 50Hertz (Baltic Sea)
- `[172]` **Wind Offshore (TenneT)**: offshore wind output, TenneT (North Sea)
- `[179]` **Wind Onshore (50Hertz)**: onshore wind output, 50Hertz zone
- `[177]` **Wind Onshore (APG)**: onshore wind output, Austria (APG)
- `[180]` **Wind Onshore (Amprion)**: onshore wind output, Amprion zone
- `[178]` **Wind Onshore (Creos)**: onshore wind output, Luxembourg (Creos)
- `[181]` **Wind Onshore (TenneT)**: onshore wind output, TenneT zone
- `[182]` **Wind Onshore (TransnetBW)**: onshore wind output, TransnetBW zone

### Challenge 6. SMARD Generation Challenge (all generation types): 72h horizon, 1h frequency

**Challenge ID:** 6

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast electricity generation (MW) broken down by energy source and transmission control area. A representative round carried 16 series covering lignite, photovoltaics (solar), offshore wind and onshore wind across the German, Austrian and Luxembourg control areas. The full catalogue for this challenge can reach roughly two dozen source-by-area series and varies between rounds.

**Companion challenge:** ID 3 (same series at 24h horizon, 15-min frequency).

**Series (16)**

- `[18]` **Lignite (50Hertz)**: brown-coal (lignite) output, 50Hertz zone
- `[19]` **Lignite (Amprion)**: brown-coal (lignite) output, Amprion zone
- `[138]` **Photovoltaic (50Hertz)**: solar PV output, 50Hertz zone
- `[139]` **Photovoltaic (APG)**: solar PV output, Austria (APG)
- `[140]` **Photovoltaic (Amprion)**: solar PV output, Amprion zone
- `[137]` **Photovoltaic (Creos)**: solar PV output, Luxembourg (Creos)
- `[141]` **Photovoltaic (TenneT)**: solar PV output, TenneT zone
- `[142]` **Photovoltaic (TransnetBW)**: solar PV output, TransnetBW zone
- `[171]` **Wind Offshore (50Hertz)**: offshore wind output, 50Hertz (Baltic Sea)
- `[172]` **Wind Offshore (TenneT)**: offshore wind output, TenneT (North Sea)
- `[179]` **Wind Onshore (50Hertz)**: onshore wind output, 50Hertz zone
- `[177]` **Wind Onshore (APG)**: onshore wind output, Austria (APG)
- `[180]` **Wind Onshore (Amprion)**: onshore wind output, Amprion zone
- `[178]` **Wind Onshore (Creos)**: onshore wind output, Luxembourg (Creos)
- `[181]` **Wind Onshore (TenneT)**: onshore wind output, TenneT zone
- `[182]` **Wind Onshore (TransnetBW)**: onshore wind output, TransnetBW zone

## Gridstatus: US electricity ISOs/RTOs (CAISO & NYISO)

### Challenge 7. Gridstatus Hub / Zone Market Price Challenge: 24h horizon, 15-min frequency

**Challenge ID:** 7

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast US locational marginal prices (LMPs, $/MWh) at trading hubs and load zones. The 18 series cover California's three CAISO trading hubs and the fifteen NYISO pricing locations (eleven New York load zones plus four external proxy interfaces to neighbouring markets).

**Companion challenge:** ID 10 (same series at 72h horizon, 1h frequency).

**Series (18)**

- `[204]` **CAISO NP15**: NorthPath-15 hub price (northern California)
- `[205]` **CAISO SP15**: SouthPath-15 hub price (southern California)
- `[206]` **CAISO ZP26**: ZonePath-26 hub price (central California)
- `[261]` **NYISO CAPITL**: Capital zone price (Albany area)
- `[262]` **NYISO CENTRL**: Central New York zone price
- `[263]` **NYISO DUNWOD**: Dunwoodie zone price (lower Hudson)
- `[264]` **NYISO GENESE**: Genesee zone price
- `[265]` **NYISO H Q**: Hydro-Québec proxy interface price
- `[266]` **NYISO HUD VL**: Hudson Valley zone price
- `[267]` **NYISO LONGIL**: Long Island zone price
- `[268]` **NYISO MHK VL**: Mohawk Valley zone price
- `[269]` **NYISO MILLWD**: Millwood zone price
- `[270]` **NYISO N.Y.C.**: New York City zone price
- `[271]` **NYISO NORTH**: North zone price (Plattsburgh area)
- `[272]` **NYISO NPX**: New England proxy interface price
- `[273]` **NYISO O H**: Ontario proxy interface price
- `[274]` **NYISO PJM**: PJM proxy interface price
- `[275]` **NYISO WEST**: Western New York zone price (Buffalo area)

### Challenge 10. Gridstatus Hub / Zone Market Price Challenge: 72h horizon, 1h frequency

**Challenge ID:** 10

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast US locational marginal prices (LMPs, $/MWh) at trading hubs and load zones. The 18 series cover California's three CAISO trading hubs and the fifteen NYISO pricing locations (eleven New York load zones plus four external proxy interfaces to neighbouring markets).

**Companion challenge:** ID 7 (same series at 24h horizon, 15-min frequency).

**Series (18)**

- `[204]` **CAISO NP15**: NorthPath-15 hub price (northern California)
- `[205]` **CAISO SP15**: SouthPath-15 hub price (southern California)
- `[206]` **CAISO ZP26**: ZonePath-26 hub price (central California)
- `[261]` **NYISO CAPITL**: Capital zone price (Albany area)
- `[262]` **NYISO CENTRL**: Central New York zone price
- `[263]` **NYISO DUNWOD**: Dunwoodie zone price (lower Hudson)
- `[264]` **NYISO GENESE**: Genesee zone price
- `[265]` **NYISO H Q**: Hydro-Québec proxy interface price
- `[266]` **NYISO HUD VL**: Hudson Valley zone price
- `[267]` **NYISO LONGIL**: Long Island zone price
- `[268]` **NYISO MHK VL**: Mohawk Valley zone price
- `[269]` **NYISO MILLWD**: Millwood zone price
- `[270]` **NYISO N.Y.C.**: New York City zone price
- `[271]` **NYISO NORTH**: North zone price (Plattsburgh area)
- `[272]` **NYISO NPX**: New England proxy interface price
- `[273]` **NYISO O H**: Ontario proxy interface price
- `[274]` **NYISO PJM**: PJM proxy interface price
- `[275]` **NYISO WEST**: Western New York zone price (Buffalo area)

## Gridstatus: US electricity ISOs/RTOs (NYISO)

### Challenge 8. Gridstatus Load Challenge: 24h horizon, 15-min frequency

**Challenge ID:** 8

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast electricity demand (load, in MW) across the eleven NYISO pricing zones that partition New York State.

**Companion challenge:** ID 11 (same series at 72h horizon, 1h frequency).

**Series (11)**

- `[214]` **CAPITL**: Capital region demand (Albany area)
- `[215]` **CENTRL**: Central New York demand
- `[216]` **DUNWOD**: Dunwoodie demand (lower Hudson)
- `[217]` **GENESE**: Genesee demand
- `[218]` **HUD VL**: Hudson Valley demand
- `[219]` **LONGIL**: Long Island demand
- `[220]` **MHK VL**: Mohawk Valley demand
- `[221]` **MILLWD**: Millwood demand
- `[222]` **N.Y.C.**: New York City demand
- `[224]` **NORTH**: North New York demand (Plattsburgh area)
- `[225]` **WEST**: Western New York demand (Buffalo area)

### Challenge 11. Gridstatus Load Challenge: 72h horizon, 1h frequency

**Challenge ID:** 11

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast electricity demand (load, in MW) across the eleven NYISO pricing zones that partition New York State.

**Companion challenge:** ID 8 (same series at 24h horizon, 15-min frequency).

**Series (11)**

- `[214]` **CAPITL**: Capital region demand (Albany area)
- `[215]` **CENTRL**: Central New York demand
- `[216]` **DUNWOD**: Dunwoodie demand (lower Hudson)
- `[217]` **GENESE**: Genesee demand
- `[218]` **HUD VL**: Hudson Valley demand
- `[219]` **LONGIL**: Long Island demand
- `[220]` **MHK VL**: Mohawk Valley demand
- `[221]` **MILLWD**: Millwood demand
- `[222]` **N.Y.C.**: New York City demand
- `[224]` **NORTH**: North New York demand (Plattsburgh area)
- `[225]` **WEST**: Western New York demand (Buffalo area)

## Gridstatus: US electricity ISOs/RTOs (CAISO & NYISO)

### Challenge 9. Gridstatus Generation Challenge (all generation types ISO): 24h horizon, 15-min frequency

**Challenge ID:** 9

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast electricity generation (MW) broken down by fuel type, the ISO "fuel mix." A representative round carried 14 series: nine CAISO fuel categories and five NYISO categories. The full catalogue for this challenge can reach roughly 17 series and varies between rounds.

**Companion challenge:** ID 12 (same series at 72h horizon, 1h frequency).

**Series (14)**

- `[183]` **CAISO Batteries**: battery storage net discharge
- `[184]` **CAISO Biogas**: biogas-fired generation
- `[185]` **CAISO Biomass**: biomass-fired generation
- `[186]` **CAISO Geothermal**: geothermal generation
- `[188]` **CAISO LargeHydro**: large hydro generation
- `[189]` **CAISO NaturalGas**: natural-gas-fired generation
- `[192]` **CAISO SmallHydro**: small hydro generation
- `[191]` **CAISO Solar**: solar generation
- `[193]` **CAISO Wind**: wind generation
- `[207]` **NYISO DualFuel**: dual-fuel (gas/oil) generation
- `[208]` **NYISO Hydro**: hydro generation
- `[209]` **NYISO NaturalGas**: natural-gas-fired generation
- `[212]` **NYISO OtherRenewable**: other renewable generation
- `[213]` **NYISO Wind**: wind generation

### Challenge 12. Gridstatus Generation Challenge (all generation types ISO): 72h horizon, 1h frequency

**Challenge ID:** 12

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast electricity generation (MW) broken down by fuel type, the ISO "fuel mix." A representative round carried 14 series: nine CAISO fuel categories and five NYISO categories. The full catalogue for this challenge can reach roughly 17 series and varies between rounds.

**Companion challenge:** ID 9 (same series at 24h horizon, 15-min frequency).

**Series (14)**

- `[183]` **CAISO Batteries**: battery storage net discharge
- `[184]` **CAISO Biogas**: biogas-fired generation
- `[185]` **CAISO Biomass**: biomass-fired generation
- `[186]` **CAISO Geothermal**: geothermal generation
- `[188]` **CAISO LargeHydro**: large hydro generation
- `[189]` **CAISO NaturalGas**: natural-gas-fired generation
- `[192]` **CAISO SmallHydro**: small hydro generation
- `[191]` **CAISO Solar**: solar generation
- `[193]` **CAISO Wind**: wind generation
- `[207]` **NYISO DualFuel**: dual-fuel (gas/oil) generation
- `[208]` **NYISO Hydro**: hydro generation
- `[209]` **NYISO NaturalGas**: natural-gas-fired generation
- `[212]` **NYISO OtherRenewable**: other renewable generation
- `[213]` **NYISO Wind**: wind generation

## Fingrid: Finnish national grid (Fingrid open data)

### Challenge 13. FINGRID Challenge (mixed): 24h horizon, 15-min frequency

**Challenge ID:** 13

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast a mixed bundle of Finnish power-system series from Fingrid's open data, combining generation by plant type, total production, consumption series and derived intensity indicators in a single challenge.

**Companion challenge:** ID 14 (same series at 72h horizon, 1h frequency).

**Series (9)**

- `[410]` **cogeneration_district_heating_power_plant_generation**: CHP output linked to district heating
- `[415]` **industrial_cogeneration_power_plant_generation**: industrial combined-heat-and-power output
- `[414]` **hydropower_power_plant_generation**: hydropower generation
- `[419]` **wind_onshore_power_plant_generation**: onshore wind generation
- `[412]` **electricity_production**: total Finnish electricity production
- `[411]` **electric_boiler_consumption**: power drawn by electric boilers (power-to-heat)
- `[416]` **net_consumption**: national net electricity consumption
- `[413]` **emission_factor_consumed_electricity**: carbon intensity of consumed electricity (gCO₂/kWh)
- `[417]` **non_fossil_generation_share**: share of generation from non-fossil sources (%)

### Challenge 14. FINGRID Challenge (mixed): 72h horizon, 1h frequency

**Challenge ID:** 14

**Frequency:** hourly (PT1H) · **Horizon:** 72 hours (P3D) = 72 steps · **Context length:** 1,000 observations per series

Forecast a mixed bundle of Finnish power-system series from Fingrid's open data, combining generation by plant type, total production, consumption series and derived intensity indicators in a single challenge.

**Companion challenge:** ID 13 (same series at 24h horizon, 15-min frequency).

**Series (9)**

- `[410]` **cogeneration_district_heating_power_plant_generation**: CHP output linked to district heating
- `[415]` **industrial_cogeneration_power_plant_generation**: industrial combined-heat-and-power output
- `[414]` **hydropower_power_plant_generation**: hydropower generation
- `[419]` **wind_onshore_power_plant_generation**: onshore wind generation
- `[412]` **electricity_production**: total Finnish electricity production
- `[411]` **electric_boiler_consumption**: power drawn by electric boilers (power-to-heat)
- `[416]` **net_consumption**: national net electricity consumption
- `[413]` **emission_factor_consumed_electricity**: carbon intensity of consumed electricity (gCO₂/kWh)
- `[417]` **non_fossil_generation_share**: share of generation from non-fossil sources (%)

## Tankerkönig: German retail fuel prices (Federal Cartel Office feed)

### Challenge 29. Tankerkönig Fuel Price Challenge: 24h horizon, 15-min frequency

**Challenge ID:** 29

**Frequency:** 15-minute (PT15M) · **Horizon:** 24 hours (P1D) = 96 steps · **Context length:** 1,000 observations per series

Forecast German retail road-fuel prices (€/litre) reported by filling stations to the Federal Cartel Office's market-transparency unit and published through the Tankerkönig feed. The series cover three fuel grades (diesel, Super E5 and Super E10) for three cities (Berlin, Hamburg, Paderborn).

**Companion challenge:** ID 30 (same series at 24h horizon, 1h frequency).

**Series (9)**

- `[1539192]` **Berlin (Diesel)**: diesel price in Berlin
- `[1539191]` **Berlin (E10)**: Super E10 price in Berlin
- `[1539190]` **Berlin (E5)**: Super E5 price in Berlin
- `[1539189]` **Hamburg (Diesel)**: diesel price in Hamburg
- `[1539188]` **Hamburg (E10)**: Super E10 price in Hamburg
- `[1539187]` **Hamburg (E5)**: Super E5 price in Hamburg
- `[1539198]` **Paderborn (Diesel)**: diesel price in Paderborn
- `[1539197]` **Paderborn (E10)**: Super E10 price in Paderborn
- `[1539196]` **Paderborn (E5)**: Super E5 price in Paderborn

### Challenge 30. Tankerkönig Fuel Price Challenge: 24h horizon, 1h frequency

**Challenge ID:** 30

**Frequency:** hourly (PT1H) · **Horizon:** 24 hours (P1D) = 24 steps · **Context length:** 1,000 observations per series

Forecast German retail road-fuel prices (€/litre) reported by filling stations to the Federal Cartel Office's market-transparency unit and published through the Tankerkönig feed. The series cover three fuel grades (diesel, Super E5 and Super E10) for three cities (Berlin, Hamburg, Paderborn).

**Companion challenge:** ID 29 (same series at 24h horizon, 15-min frequency).

**Series (9)**

- `[1539192]` **Berlin (Diesel)**: diesel price in Berlin
- `[1539191]` **Berlin (E10)**: Super E10 price in Berlin
- `[1539190]` **Berlin (E5)**: Super E5 price in Berlin
- `[1539189]` **Hamburg (Diesel)**: diesel price in Hamburg
- `[1539188]` **Hamburg (E10)**: Super E10 price in Hamburg
- `[1539187]` **Hamburg (E5)**: Super E5 price in Hamburg
- `[1539198]` **Paderborn (Diesel)**: diesel price in Paderborn
- `[1539197]` **Paderborn (E10)**: Super E10 price in Paderborn
- `[1539196]` **Paderborn (E5)**: Super E5 price in Paderborn
