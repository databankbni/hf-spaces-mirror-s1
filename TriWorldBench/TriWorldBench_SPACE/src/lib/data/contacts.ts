import { getDb } from "@/lib/db";
import { all, get as dbGet } from "@/lib/db/helpers";
import type { ContactInfo, OtherInformation } from "@/lib/db/schema";
import { localized } from "@/lib/i18n";

export function getContacts(): ContactInfo[] {
  return all<ContactInfo>(getDb().prepare("SELECT * FROM contact_info ORDER BY sort_order, id")).map((contact) => ({
    ...contact,
    labelText: localized(contact.label_en ?? contact.label, contact.label_zh),
    descriptionText: localized(contact.description_en, contact.description_zh),
  }));
}

export function getOtherInformation(): OtherInformation | null {
  return dbGet<OtherInformation>(getDb().prepare("SELECT * FROM other_information ORDER BY id LIMIT 1"));
}
