import type { Metadata } from "next";
import CtaBanner from "@/components/CtaBanner";
import PlantVideo from "@/components/PlantVideo";
import TwinLauncher from "@/components/TwinLauncher";
import RevealLines from "@/components/motion/RevealLines";
import Reveal from "@/components/motion/Reveal";

export const metadata: Metadata = {
  title: "Digital Twins",
  description:
    "Digital twins that combine real equipment data, physics models and machine learning to monitor and predict the performance of process equipment.",
};

const capabilities = [
  {
    title: "Monitor",
    text: "Tracks live performance against how the equipment should be running — so drift, fouling and losses show up the day they start.",
  },
  {
    title: "Predict",
    text: "Forecasts how performance will change over time and under new conditions — before it happens on the plant.",
  },
];

const ingredients = [
  {
    title: "Real equipment data",
    text: "Historian and sensor data — temperatures, pressures, flows, vibration — straight from your plant.",
  },
  {
    title: "Physics model",
    text: "First-principles thermodynamics, heat & mass balances and equipment rating that keep every prediction physically sound.",
  },
  {
    title: "ML model",
    text: "Machine learning trained on operating history captures what physics alone misses and keeps the twin calibrated.",
  },
];

const benefits = [
  {
    title: "Performance monitoring",
    text: "See the real-time efficiency and health of every asset against its design and its best-ever performance.",
  },
  {
    title: "Prediction",
    text: "Forecast how equipment will perform next week, next month or next campaign — and plan around it.",
  },
  {
    title: "Fault detection",
    text: "Spot abnormal behaviour such as fouling, leaks, cavitation or catalyst decline long before alarms trip.",
  },
  {
    title: "Energy optimization",
    text: "Find the operating point that delivers the same output with less steam, power and fuel.",
  },
  {
    title: "Predictive maintenance",
    text: "Clean, repair or replace based on actual condition — not fixed calendars — and avoid unplanned shutdowns.",
  },
  {
    title: "What-if analysis",
    text: "Test new feeds, rates or setpoints on the twin first, with zero risk to the real plant.",
  },
];

const label = "text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep";
const heading = "font-semibold uppercase leading-[0.92] tracking-[-0.035em]";

export default function DigitalTwinsPage() {
  return (
    <>
      <section className="mx-auto w-full max-w-7xl px-6 pb-20 pt-40 lg:px-12 lg:pt-48">
        <RevealLines as="p" className={label} lines={["Digital Twins"]} />
        <RevealLines
          as="h1"
          delay={0.1}
          className={`mt-6 text-[clamp(2.6rem,7vw,7rem)] ${heading}`}
          lines={[
            "A living model",
            <span key="machine">
              of every <span className="text-accent">machine</span>
            </span>,
            "you run.",
          ]}
        />
        <Reveal delay={0.4} className="mt-10 max-w-2xl">
          <p className="text-lg leading-relaxed text-muted">
            A digital twin is a digital model of real equipment. It runs alongside the actual machine, continuously
            monitoring how it performs and predicting how it will behave next.
          </p>
        </Reveal>
      </section>

      <section className="mx-auto w-full max-w-7xl px-6 pb-28 lg:px-12">
        <div className="grid gap-8 lg:grid-cols-2 lg:items-end">
          <div>
            <RevealLines as="p" className={label} lines={["Twins we've built"]} />
            <RevealLines
              as="h2"
              delay={0.1}
              className={`mt-5 text-[clamp(2.4rem,5vw,4.5rem)] ${heading}`}
              lines={["Explore a", <span key="twin" className="text-accent">digital twin</span>]}
            />
          </div>
          <Reveal delay={0.2}>
            <p className="max-w-lg leading-relaxed text-muted">
              Pick a piece of equipment to see how its twin works, what it tracks and the value it delivers.
            </p>
          </Reveal>
        </div>
        <div className="mt-14">
          <TwinLauncher />
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-6 pb-28 lg:px-12">
        <RevealLines as="p" className={label} lines={["What a twin does"]} />
        <div className="mt-8 grid border-t border-line md:grid-cols-2">
          {capabilities.map((item, i) => (
            <Reveal
              key={item.title}
              delay={0.1 * i}
              className={`py-10 md:pr-10 ${i > 0 ? "border-t border-line md:border-l md:border-t-0 md:pl-10" : ""}`}
            >
              <h2 className={`text-3xl sm:text-4xl ${heading}`}>
                <span className="mr-3 font-mono text-sm font-normal tracking-normal text-muted">0{i + 1}</span>
                {item.title}
              </h2>
              <p className="mt-4 max-w-md leading-relaxed text-muted">{item.text}</p>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="border-y border-line bg-white">
        <div className="mx-auto max-w-7xl px-6 py-28 lg:px-12">
          <RevealLines as="p" className={label} lines={["What you gain"]} />
          <RevealLines
            as="h2"
            delay={0.1}
            className={`mt-5 text-[clamp(2.4rem,5vw,4.5rem)] ${heading}`}
            lines={["Six ways a twin", <span key="pays" className="text-accent">pays back</span>]}
          />

          <div className="mt-16 grid border-t border-line sm:grid-cols-2 lg:grid-cols-3">
            {benefits.map((benefit, i) => (
              <Reveal key={benefit.title} delay={0.06 * (i % 3)} className="group border-b border-line py-10 sm:pr-10">
                <span className="font-mono text-sm text-muted transition-colors group-hover:text-accent">0{i + 1}</span>
                <h3 className="mt-5 text-2xl font-semibold uppercase tracking-tight transition-transform duration-500 group-hover:translate-x-2">
                  {benefit.title}
                </h3>
                <p className="mt-3 max-w-sm leading-relaxed text-muted">{benefit.text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="px-6 pt-28 lg:px-12">
        <Reveal className="relative mx-auto h-[60svh] min-h-[380px] max-w-7xl overflow-hidden rounded-3xl">
          <PlantVideo />
          <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-ink/70 via-ink/10 to-transparent" />
          <p className="absolute inset-x-0 bottom-0 p-8 text-[clamp(1.5rem,3.5vw,2.75rem)] font-semibold uppercase leading-[0.95] tracking-[-0.03em] text-paper sm:p-12">
            Real equipment. Real data.
            <br />
            <span className="text-peach">A model that keeps learning.</span>
          </p>
        </Reveal>
      </section>

      <section className="mx-auto w-full max-w-7xl px-6 py-28 lg:px-12">
        <div className="grid gap-8 lg:grid-cols-2 lg:items-end">
          <div>
            <RevealLines as="p" className={label} lines={["How it's built"]} />
            <RevealLines
              as="h2"
              delay={0.1}
              className={`mt-5 text-[clamp(2.4rem,5vw,4.5rem)] ${heading}`}
              lines={["Three inputs,", <span key="one" className="text-accent">one twin</span>]}
            />
          </div>
          <Reveal delay={0.2}>
            <p className="max-w-lg leading-relaxed text-muted">
              Data alone can drift and physics alone can miss real-world behaviour. We combine both into a hybrid
              model that is accurate, explainable and stays in step with the equipment.
            </p>
          </Reveal>
        </div>

        <div className="mt-16 grid gap-10 lg:grid-cols-4 lg:gap-6">
          {ingredients.map((item, i) => (
            <Reveal key={item.title} delay={0.1 * i} className="relative">
              {i > 0 && <Operator symbol="+" />}
              <div className="h-full rounded-2xl border border-line bg-white p-8">
                <span className="font-mono text-xs text-muted">0{i + 1}</span>
                <h3 className="mt-6 text-xl font-semibold uppercase tracking-tight">{item.title}</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-muted">{item.text}</p>
              </div>
            </Reveal>
          ))}
          <Reveal delay={0.3} className="relative">
            <Operator symbol="=" />
            <div className="h-full rounded-2xl bg-accent p-8 text-white">
              <span className="font-mono text-xs text-white/70">Result</span>
              <h3 className="mt-6 text-xl font-semibold uppercase tracking-tight">Hybrid digital twin</h3>
              <p className="mt-3 text-[15px] leading-relaxed text-white/85">
                Accurate like data, reliable like physics — and always in sync with the real equipment.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      <CtaBanner title="Ready to twin your equipment?" />
    </>
  );
}

function Operator({ symbol }: { symbol: string }) {
  return (
    <span
      aria-hidden="true"
      className="absolute -top-10 left-1/2 z-10 flex h-10 w-10 -translate-x-1/2 items-center justify-center rounded-full border border-line bg-paper text-lg font-semibold text-accent-deep lg:-left-8 lg:top-1/2 lg:translate-x-0 lg:-translate-y-1/2"
    >
      {symbol}
    </span>
  );
}
