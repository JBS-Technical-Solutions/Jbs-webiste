export type EquipmentModel = {
  slug: "heat-exchanger" | "methanol-reformer" | "pump";
  name: string;
  category: string;
  summary: string;
  description: string;
  tracks: string[];
  outcomes: string[];
};

export const models: EquipmentModel[] = [
  {
    slug: "heat-exchanger",
    name: "Heat Exchanger",
    category: "Heat transfer",
    summary: "Live thermal performance, fouling and cleaning forecasts.",
    description:
      "Our heat exchanger twin compares how the exchanger is actually performing against how it should perform at today's flows and temperatures. Rigorous thermal rating keeps the physics honest, while machine learning learns the exchanger's own fouling behaviour — so you know exactly how much duty you are losing and when cleaning will pay for itself.",
    tracks: [
      "Inlet & outlet temperatures",
      "Heat duty & overall U-value",
      "Fouling resistance",
      "Shell & tube-side pressure drop",
      "Approach temperature",
      "Energy lost to fouling",
    ],
    outcomes: [
      "Plan cleanings on condition, not on the calendar",
      "Reclaim lost heat and cut furnace fuel",
      "Catch tube leaks and bypassing early",
    ],
  },
  {
    slug: "methanol-reformer",
    name: "Methanol Reformer",
    category: "Reaction engineering",
    summary: "Methanol decomposition to hydrogen: conversion, bed temperatures and heat demand.",
    description:
      "The methanol reformer twin solves CH₃OH → CO + 2H₂ along a jacket-heated packed bed. Set feed temperature, pressure and flow — physics, hybrid and PINN engines return axial temperature, conversion, pressure drop and heat duty.",
    tracks: [
      "Axial bed temperature profile",
      "Methanol conversion",
      "Outlet pressure & bed pressure drop",
      "Heat duty from the heating jacket",
      "Feed temperature, pressure & flow",
    ],
    outcomes: [
      "Find the feed conditions that maximise hydrogen output",
      "Size heating duty before changing throughput",
      "Spot cold zones and under-performing catalyst early",
    ],
  },
  {
    slug: "pump",
    name: "Water Pump",
    category: "Rotating equipment",
    summary: "Operating point, efficiency and failure risk, always on.",
    description:
      "The pump twin places the live operating point on the pump's own performance curve and tracks how far it drifts from best efficiency. Combining pump hydraulics with machine learning on vibration and power data, it flags cavitation risk, wear and energy waste early — turning surprise failures into planned maintenance.",
    tracks: [
      "Flow, head & operating point",
      "Efficiency vs. best efficiency point",
      "NPSH margin & cavitation risk",
      "Power & energy consumption",
      "Vibration & bearing temperature",
      "Remaining useful life",
    ],
    outcomes: [
      "Cut pumping energy by running closer to BEP",
      "Avoid unplanned trips and seal failures",
      "Maintain based on real wear, not run-hours",
    ],
  },
];
