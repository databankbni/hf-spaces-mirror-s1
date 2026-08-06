% =====================================================================
% genealogy_rules.pl -- Genealogical consistency rule base (v1).
% MemorialWiki-4C verification layer (C1 Correct + C4 Complete).
%
% Three-valued semantics, implemented conservatively:
%   finding(violation, Code, Args)  provably impossible          (C1 hard)
%   finding(warning,   Code, Args)  provable but implausible /
%                                   likely data-entry error      (C1 soft)
%   gap(Entity, What)               required knowledge missing   (C4)
%   undetermined(Check, Entity)     check not decidable from
%                                   available (partial) dates
%
% A check fires ONLY when it is provable from known date components.
% Partial dates (atom 'unknown' in any slot) never produce violations
% by guesswork -- they degrade to undetermined/gap instead.
%
% Requires SWI-Prolog >= 8 (tabling used for cycle-safe ancestry).
% =====================================================================

:- dynamic person/1, person_name/2, sex/2,
           birth/2, death/2, approx_date/2,
           family/1, husband/2, wife/2, child_in/2,
           marriage/2, approx_marriage/1, parse_issue/1.

:- discontiguous finding/3.
:- discontiguous gap/2.
:- discontiguous undetermined/2.

% ---------------------------------------------------------------------
% 1. Partial-date primitives (conservative comparison)
% ---------------------------------------------------------------------

known_year(date(Y, _, _), Y) :- integer(Y).

% proved_before(+D1, +D2): D1 is PROVABLY strictly before D2,
% using only the known components. Never guesses.
proved_before(date(Y1, _, _), date(Y2, _, _)) :-
    integer(Y1), integer(Y2), Y1 < Y2.
proved_before(date(Y1, M1, _), date(Y2, M2, _)) :-
    integer(Y1), integer(Y2), Y1 =:= Y2,
    integer(M1), integer(M2), M1 < M2.
proved_before(date(Y1, M1, D1), date(Y2, M2, D2)) :-
    integer(Y1), integer(Y2), Y1 =:= Y2,
    integer(M1), integer(M2), M1 =:= M2,
    integer(D1), integer(D2), D1 < D2.

% Year-level elapsed-time bounds between two partial dates.
% True elapsed whole years A satisfies: years_min =< A =< years_max.
years_max(date(Y1, _, _), date(Y2, _, _), A) :-
    integer(Y1), integer(Y2), A is Y2 - Y1.
years_min(date(Y1, _, _), date(Y2, _, _), A) :-
    integer(Y1), integer(Y2), A is Y2 - Y1 - 1.

% ---------------------------------------------------------------------
% 2. Kinship layer (cycle-safe via tabling)
% ---------------------------------------------------------------------

parent_of(P, C) :- child_in(C, F), husband(F, P).
parent_of(P, C) :- child_in(C, F), wife(F, P).

mother_of(M, C) :- child_in(C, F), wife(F, M).
father_of(P, C) :- child_in(C, F), husband(F, P).

spouse_in(F, P) :- husband(F, P).
spouse_in(F, P) :- wife(F, P).

% Cycle-safe ancestry WITHOUT tabling.
% Rationale: tabled predicates cache answers across consults; when the
% dynamic fact base is replaced between runs (same engine), stale table
% entries from a previous file can leak into the next verification
% (observed on Windows SWI-Prolog). A visited-set walk has no cache,
% no cross-run state, and still terminates on cyclic data.
ancestor(A, D) :- ancestor_walk(A, D, [A]).

ancestor_walk(A, D, _) :- parent_of(A, D).
ancestor_walk(A, D, Seen) :-
    parent_of(A, X),
    \+ memberchk(X, Seen),
    ancestor_walk(X, D, [X|Seen]).

% ---------------------------------------------------------------------
% 3. C1 hard violations (logically impossible)
% ---------------------------------------------------------------------

% V01: death provably before birth
finding(violation, death_before_birth, [P]) :-
    person(P), birth(P, B), death(P, D),
    proved_before(D, B).

% V02: ancestry cycle (a person is their own ancestor)
finding(violation, ancestry_cycle, [P]) :-
    person(P), ancestor(P, P).

% V03: parent provably born after child
finding(violation, parent_born_after_child, [Par, C]) :-
    parent_of(Par, C), birth(Par, BP), birth(C, BC),
    proved_before(BC, BP).

% V04: parent provably younger than 12 at child's birth
%      (max possible age still below biological floor)
finding(violation, parent_under_12_at_birth, [Par, C]) :-
    parent_of(Par, C), birth(Par, BP), birth(C, BC),
    years_max(BP, BC, A), A >= 0, A < 12.

% V05: mother provably older than 70 at child's birth
finding(violation, mother_over_70_at_birth, [M, C]) :-
    mother_of(M, C), birth(M, BM), birth(C, BC),
    years_min(BM, BC, A), A > 70.

% V06: child provably born after mother's death
finding(violation, born_after_mother_death, [M, C]) :-
    mother_of(M, C), death(M, DM), birth(C, BC),
    proved_before(DM, BC).

% V07: child born more than one full year after father's death
%      (posthumous birth within ~9 months is legitimate, so the
%       year-level test allows Yb =< Yd + 1)
finding(violation, born_after_father_death, [F, C]) :-
    father_of(F, C),
    death(F, date(Yd, _, _)), integer(Yd),
    birth(C, date(Yb, _, _)), integer(Yb),
    Yb > Yd + 1.

% V08: lifespan provably exceeds 125 years
finding(violation, lifespan_over_125, [P]) :-
    person(P), birth(P, B), death(P, D),
    years_min(B, D, A), A > 125.

% V09: marriage provably after a spouse's death
finding(violation, married_after_death, [P, F]) :-
    spouse_in(F, P), marriage(F, MD), death(P, DD),
    proved_before(DD, MD).

% V10: marriage provably before a spouse's birth
finding(violation, married_before_birth, [P, F]) :-
    spouse_in(F, P), marriage(F, MD), birth(P, BD),
    proved_before(MD, BD).

% V11: same person recorded as both husband and wife of one family
finding(violation, spouse_role_conflict, [P, F]) :-
    husband(F, P), wife(F, P).

% V12: a person recorded as a child of the same family twice or as
%      their own parent within one family
finding(violation, self_parent, [P, F]) :-
    child_in(P, F), spouse_in(F, P).

% ---------------------------------------------------------------------
% 4. C1 soft warnings (possible but implausible / needs review)
% ---------------------------------------------------------------------

% W01: parent aged 12-15 at child's birth
finding(warning, parent_under_16_at_birth, [Par, C]) :-
    parent_of(Par, C), birth(Par, BP), birth(C, BC),
    years_max(BP, BC, A), A >= 12, A < 16.

% W02: mother aged 56-70 at child's birth
finding(warning, mother_over_55_at_birth, [M, C]) :-
    mother_of(M, C), birth(M, BM), birth(C, BC),
    years_min(BM, BC, A), A > 55, A =< 70.

% W03: lifespan 111-125 years
finding(warning, lifespan_over_110, [P]) :-
    person(P), birth(P, B), death(P, D),
    years_min(B, D, A), A > 110, A =< 125.

% W04: married provably younger than 16
finding(warning, married_under_16, [P, F]) :-
    spouse_in(F, P), marriage(F, MD), birth(P, BD),
    years_max(BD, MD, A), A >= 0, A < 16.

% W05 / W06: recorded sex conflicts with spousal role
%      (warning, not violation: may be data entry error or a
%       same-sex union recorded through legacy GEDCOM roles)
finding(warning, husband_recorded_female, [P, F]) :-
    husband(F, P), sex(P, f).
finding(warning, wife_recorded_male, [P, F]) :-
    wife(F, P), sex(P, m).

% W07: father provably older than 80 at child's birth
finding(warning, father_over_80_at_birth, [F, C]) :-
    father_of(F, C), birth(F, BF), birth(C, BC),
    years_min(BF, BC, A), A > 80.

% W08: finding rests on an approximate date (meta-warning that a
%      violation involving this person uses ABT/EST/BEF/AFT data)
finding(warning, violation_uses_approx_date, [P]) :-
    approx_date(P, _),
    finding(violation, _, Args),
    memberchk(P, Args).

% ---------------------------------------------------------------------
% 5. C4 completeness gaps (missing required knowledge)
% ---------------------------------------------------------------------

gap(P, name) :-
    person(P), \+ person_name(P, _).

gap(P, birth_date) :-
    person(P), \+ birth(P, _).

gap(P, birth_year) :-
    birth(P, date(Y, _, _)), \+ integer(Y).

gap(P, sex) :-
    person(P), \+ sex(P, _).

gap(F, marriage_date) :-
    family(F), husband(F, _), wife(F, _), \+ marriage(F, _).

% ---------------------------------------------------------------------
% 6. Undetermined checks (not decidable from available data)
% ---------------------------------------------------------------------

undetermined(lifespan_check, P) :-
    person(P), death(P, _),
    \+ ( birth(P, date(Y, _, _)), integer(Y) ).

undetermined(parent_age_check, Par-C) :-
    parent_of(Par, C),
    ( \+ ( birth(Par, date(Y1, _, _)), integer(Y1) )
    ; \+ ( birth(C, date(Y2, _, _)), integer(Y2) )
    ).

% ---------------------------------------------------------------------
% 7. Report drivers (called from Python via pyswip)
% ---------------------------------------------------------------------

all_findings(L) :-
    findall(f(Sev, Code, Args), finding(Sev, Code, Args), L0),
    sort(L0, L).

all_gaps(L) :-
    findall(g(E, W), gap(E, W), L0),
    sort(L0, L).

all_undetermined(L) :-
    findall(u(C, E), undetermined(C, E), L0),
    sort(L0, L).
