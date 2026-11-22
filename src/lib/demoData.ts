import type { Claim } from "@/types";

/**
 * DEMO DATA ONLY.
 * These claims and sources are fabricated placeholders used to preview the UI.
 * They are NOT real fact-checking results. URLs use the reserved example.com domain.
 */
export const DEMO_FILE_NAME = "sample-document.pdf";

export const DEMO_CLAIMS: Claim[] = [
  {
    id: "c1",
    text: "Sample claim A: The global market for product X reached $50 billion in 2023.",
    page: 2,
    status: "verified",
    confidence: 94,
    explanation:
      "[DEMO] Placeholder explanation. In the real product, this will summarise how the evidence supports the claim.",
    sources: [
      {
        title: "Demo Source – Market Report",
        url: "https://example.com/demo-source-1",
        snippet: "[DEMO] Placeholder snippet from a sample source.",
      },
      {
        title: "Demo Source – Industry News",
        url: "https://example.com/demo-source-2",
        snippet: "[DEMO] Another placeholder snippet.",
      },
    ],
  },
  {
    id: "c2",
    text: "Sample claim B: Company Y was founded in 1998 by three engineers.",
    page: 3,
    status: "inaccurate",
    confidence: 78,
    explanation:
      "[DEMO] Placeholder: the claim is partly correct but a detail differs from the sample sources.",
    correction: "[DEMO] Placeholder corrected statement.",
    sources: [
      {
        title: "Demo Source – Company History",
        url: "https://example.com/demo-source-3",
        snippet: "[DEMO] Placeholder snippet showing a differing detail.",
      },
    ],
  },
  {
    id: "c3",
    text: "Sample claim C: Technology Z was banned in every country in 2020.",
    page: 5,
    status: "false",
    confidence: 91,
    explanation:
      "[DEMO] Placeholder: sample sources contradict this claim.",
    correction: "[DEMO] Placeholder corrected statement.",
    sources: [
      {
        title: "Demo Source – Policy Overview",
        url: "https://example.com/demo-source-4",
        snippet: "[DEMO] Placeholder snippet contradicting the claim.",
      },
    ],
  },
  {
    id: "c4",
    text: "Sample claim D: 72% of surveyed users prefer the new interface.",
    page: 6,
    status: "unverified",
    confidence: 32,
    explanation:
      "[DEMO] Placeholder: no reliable sample source could be found for this claim.",
    sources: [],
  },
  {
    id: "c5",
    text: "Sample claim E: The Great Example Bridge is 2,400 metres long.",
    page: 7,
    status: "verified",
    confidence: 97,
    explanation: "[DEMO] Placeholder explanation of supporting evidence.",
    sources: [
      {
        title: "Demo Source – Engineering Archive",
        url: "https://example.com/demo-source-5",
        snippet: "[DEMO] Placeholder snippet.",
      },
    ],
  },
  {
    id: "c6",
    text: "Sample claim F: Annual rainfall in Region R increased by 40% since 2010.",
    page: 9,
    status: "inaccurate",
    confidence: 70,
    explanation:
      "[DEMO] Placeholder: the figure appears overstated relative to sample sources.",
    correction: "[DEMO] Placeholder corrected figure.",
    sources: [
      {
        title: "Demo Source – Climate Data",
        url: "https://example.com/demo-source-6",
        snippet: "[DEMO] Placeholder snippet.",
      },
    ],
  },
  {
    id: "c7",
    text: "Sample claim G: Product P is the best-selling device of all time.",
    page: 10,
    status: "unverified",
    confidence: 41,
    explanation: "[DEMO] Placeholder: insufficient sample evidence either way.",
    sources: [],
  },
  {
    id: "c8",
    text: "Sample claim H: The treaty was signed in 1975 by 35 nations.",
    page: 12,
    status: "verified",
    confidence: 89,
    explanation: "[DEMO] Placeholder explanation of supporting evidence.",
    sources: [
      {
        title: "Demo Source – Historical Archive",
        url: "https://example.com/demo-source-7",
        snippet: "[DEMO] Placeholder snippet.",
      },
    ],
  },
];
