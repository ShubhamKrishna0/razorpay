/** Plain-language vocabulary.
 *
 * The people working this queue are finance ops, not engineers. Every label
 * they see comes from this one module, written to answer the question an ops
 * person actually asks: "what happened to the money, and what do I do?"
 */

export interface ExceptionMeaning {
  /** Short name shown in tables and charts. */
  label: string;
  /** One sentence: what happened to the money. */
  meaning: string;
  /** What the person working the queue should do about it. */
  action: string;
}

export const EXCEPTION_GLOSSARY: Record<string, ExceptionMeaning> = {
  MATCHED: {
    label: "Fully reconciled",
    meaning: "Order, payment and settlement all line up. Nothing to do.",
    action: "No action needed.",
  },
  MISSING_SETTLEMENT: {
    label: "Money not deposited",
    meaning: "The customer paid, but the gateway has not deposited the money yet.",
    action: "If it stays unsettled past the normal cycle, raise it with the gateway.",
  },
  MISSING_PAYMENT: {
    label: "Order never paid",
    meaning: "An order exists but no payment ever arrived for it.",
    action: "Check if the order was cancelled, or if the payment landed under different details.",
  },
  ORPHAN_PAYMENT: {
    label: "Payment with no order",
    meaning: "Money came in that does not belong to any order we know about.",
    action: "Find which order this belongs to, or flag it for refund.",
  },
  ORPHAN_SETTLEMENT: {
    label: "Deposit with no payment",
    meaning: "The gateway deposited money we have no payment record for.",
    action: "Ask the gateway which transactions this deposit covers.",
  },
  DUPLICATE: {
    label: "Charged twice",
    meaning: "The same payment appears more than once — the customer may have been double-charged.",
    action: "Confirm the double charge and refund the extra payment.",
  },
  PARTIAL_PAYMENT: {
    label: "Paid less than billed",
    meaning: "The customer paid less than the order amount.",
    action: "Decide whether to collect the balance or adjust the order.",
  },
  OVERPAYMENT: {
    label: "Paid more than billed",
    meaning: "The customer paid more than the order amount.",
    action: "Refund the excess or apply it as credit.",
  },
  SETTLEMENT_SHORTFALL: {
    label: "Deposit short",
    meaning: "The gateway deposited less than the payment even after its fee. Money is missing.",
    action: "Raise the shortfall with the gateway — this is not explained by fees.",
  },
  FEE_VARIANCE: {
    label: "Fee higher than agreed",
    meaning: "The deposit is short by exactly the fee charged — but that fee is above the contracted rate.",
    action: "Check the rate card with the gateway; the maths adds up but the rate does not.",
  },
  AMOUNT_MISMATCH: {
    label: "Amounts disagree",
    meaning: "The amounts across the three records do not line up in a way fees can explain.",
    action: "Compare the three records and decide which one is wrong.",
  },
  TIMING_MISMATCH: {
    label: "Unusually late",
    meaning: "The payment or the deposit arrived far outside the normal window.",
    action: "Usually fine once verified — confirm the late leg is the right one.",
  },
  REFUND: {
    label: "Refunded",
    meaning: "This payment was returned to the customer.",
    action: "No action if the refund was intended.",
  },
  CURRENCY_MISMATCH: {
    label: "Wrong currency",
    meaning: "The records are in different currencies.",
    action: "Check for an FX leg or a data entry error.",
  },
  MERCHANT_MISMATCH: {
    label: "Wrong account",
    meaning: "The payment references a different merchant than the order.",
    action: "Confirm which account the money should have gone to.",
  },
  UNKNOWN: {
    label: "Unclassified",
    meaning: "The engine could not determine what happened here.",
    action: "Needs a person to look at the underlying records.",
  },
};

export function exceptionLabel(type: string | null | undefined): string {
  if (!type) return "—";
  return EXCEPTION_GLOSSARY[type]?.label ?? type.replace(/_/g, " ").toLowerCase();
}

export function exceptionMeaning(type: string | null | undefined): ExceptionMeaning | null {
  return type ? (EXCEPTION_GLOSSARY[type] ?? null) : null;
}

/** Resolution lanes, in the voice of the person working the queue. */
export const LANE_GLOSSARY: Record<string, { label: string; meaning: string }> = {
  AUTO_RESOLVED: {
    label: "Closed by rules",
    meaning: "The system matched this with certainty. No one needs to look at it.",
  },
  AI_RESOLVED: {
    label: "Closed by AI, checked",
    meaning:
      "The AI explained it, and the system re-checked the arithmetic before accepting. ",
  },
  HUMAN_REVIEW: {
    label: "Needs your review",
    meaning: "Neither the rules nor the AI could safely close this. A person decides.",
  },
  HUMAN_RESOLVED: {
    label: "Closed by you",
    meaning: "A person reviewed this and closed it. Recorded in the audit trail.",
  },
  UNRESOLVED: {
    label: "Waiting for AI",
    meaning: "Queued for AI analysis.",
  },
};

export function laneLabel(lane: string | null | undefined): string {
  if (!lane) return "—";
  return LANE_GLOSSARY[lane]?.label ?? lane.replace(/_/g, " ").toLowerCase();
}
