import { getSiteInfo, getHeroContent } from "@/lib/data/site-info";
import { getEvaluationSections } from "@/lib/data/evaluation";
import { getResearchSections, getAcademicReferences } from "@/lib/data/research";
import { getParticipationInfo } from "@/lib/data/participation";
import { getVenueHost } from "@/lib/data/venue";
import { getPolicies } from "@/lib/data/policies";
import { getContacts, getOtherInformation } from "@/lib/data/contacts";
import { getLeaderboard } from "@/lib/data/leaderboard";
import { getImportantDates } from "@/lib/data/important-dates";

/** Fetch all database content used by the public site. */
export function getSharedPageData() {
  return {
    siteInfo: getSiteInfo(),
    hero: getHeroContent(),
    evaluation: getEvaluationSections(),
    research: getResearchSections(),
    references: getAcademicReferences(),
    participation: getParticipationInfo(),
    venue: getVenueHost(),
    policies: getPolicies(),
    contacts: getContacts(),
    otherInfo: getOtherInformation(),
    leaderboard: getLeaderboard("latest"),
    dates: getImportantDates(),
  };
}
