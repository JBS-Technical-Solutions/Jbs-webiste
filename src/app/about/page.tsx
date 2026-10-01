import type { Metadata } from "next";
import aboutPlant from "@/assets/about-plant.png";
import aboutEngineers from "@/assets/about-engineers.png";
import aboutOperator from "@/assets/about-operator.png";
import CtaBanner from "@/components/CtaBanner";
import RevealLines from "@/components/motion/RevealLines";
import Reveal from "@/components/motion/Reveal";
import ParallaxImage from "@/components/motion/ParallaxImage";
import { stats } from "@/lib/site";

export const metadata: Metadata = {
  title: "About",
  description:
    "JBS Technical Solutions drives innovation through data science and digitalization for the energy and chemical industries.",
};

const facts = [
  { label: "Founded", value: "2021" },
  { label: "Headquarters", value: "Greater Houston, Texas" },
  { label: "Industries", value: "Energy & Chemicals" },
];

const sectors = ["Upstream oil & gas", "Renewables", "Midstream", "Refining", "Specialty chemicals"];

const services = [
  {
    title: "Advanced Analytics",
    description:
      "Process monitoring, troubleshooting, and continuous optimization through statistical modeling, data visualization, and machine learning pipelines in Python.",
  },
  {
    title: "Digital Twins",
    description:
      "Engineering-grade digital twins built with first-principles thermodynamics, machine learning, and hybrid semi-empirical models to support technology maturation, scale-up, and advanced process control.",
  },
  {
    title: "Workflow Digitalization",
    description:
      "Modernization of core process engineering and Process Safety Management (PSM) workflows to accelerate project delivery cycles and eliminate manual errors.",
  },
  {
    title: "Strategic Development",
    description:
      "Early-stage conceptual engineering and alternative evaluation supported by rigorous Front-End Loading (FEL), techno-economic assessments, and life cycle analyses (LCA). This includes rigorous process simulation and equipment rating using industry-standard tools.",
    tools: ["Aspen Plus", "Aspen HYSYS", "Aspen EDR", "HTRI"],
  },
];

const specialities = [
  "Upstream Oil/Gas Facility",
  "Biofuels",
  "Biorefinery",
  "Process Modeling and Design",
  "Techno-Economic Analysis",
  "Technology Scale-up",
  "Early Concept Selection",
  "Project Front End Loading",
  "Project Design Basis",
  "Technology Feasibility Study",
  "Conceptual Design Studies",
  "Process Monitoring and Optimization",
];

const label = "text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep";
const heading = "font-semibold uppercase leading-[0.92] tracking-[-0.035em]";

export default function AboutPage() {
  return (
    <>
      <section className="mx-auto w-full max-w-7xl px-6 pb-20 pt-40 lg:px-12 lg:pt-48">
        <RevealLines as="p" className={label} lines={["About us"]} />
        <RevealLines
          as="h1"
          delay={0.1}
          className={`mt-6 text-[clamp(2.6rem,7vw,7rem)] ${heading}`}
          lines={[
            "Turning plant data",
            <span key="engineering">
              into <span className="text-accent">engineering</span>
            </span>,
            "intelligence.",
          ]}
        />
        <Reveal delay={0.4} className="mt-10 max-w-2xl">
          <p className="text-lg leading-relaxed text-muted">
            We partner with energy and chemical companies to transform raw operating data into high-fidelity models and
            actionable intelligence.
          </p>
        </Reveal>

        <dl className="mt-16 grid border-t border-line sm:grid-cols-3">
          {facts.map((fact, i) => (
            <Reveal
              key={fact.label}
              delay={0.1 * i}
              className={`py-8 sm:px-8 sm:first:pl-0 ${i > 0 ? "border-t border-line sm:border-l sm:border-t-0" : ""}`}
            >
              <dt className="text-xs font-semibold uppercase tracking-[0.25em] text-muted">{fact.label}</dt>
              <dd className="mt-3 text-2xl font-semibold uppercase tracking-tight sm:text-3xl">{fact.value}</dd>
            </Reveal>
          ))}
        </dl>
      </section>

      <section className="mx-auto grid w-full max-w-7xl gap-6 px-6 md:grid-cols-12 lg:px-12">
        <Reveal className="md:col-span-7">
          <ParallaxImage
            src={aboutPlant}
            alt="Engineers inspecting a process column and piping"
            sizes="(min-width: 768px) 58vw, 100vw"
            className="aspect-[3/2] rounded-2xl"
            imageClassName="object-[35%_70%]"
          />
        </Reveal>
        <Reveal delay={0.15} className="md:col-span-5 md:mt-40">
          <ParallaxImage
            src={aboutEngineers}
            alt="Two engineers discussing a project on site"
            sizes="(min-width: 768px) 42vw, 100vw"
            className="aspect-[4/3] rounded-2xl"
          />
        </Reveal>
        <Reveal className="md:col-span-5 md:col-start-2 md:-mt-10">
          <ParallaxImage
            src={aboutOperator}
            alt="Operator handling chemical containers on a plant deck"
            sizes="(min-width: 768px) 42vw, 100vw"
            className="aspect-[4/3] rounded-2xl"
          />
        </Reveal>
        <Reveal delay={0.15} className="flex flex-col justify-end md:col-span-5 md:col-start-8 md:pb-6">
          <p className={label}>From the field to the model</p>
          <p className="mt-4 text-xl font-medium leading-snug tracking-tight sm:text-2xl">
            Every model we build starts with how the equipment really runs — on site, under real operating
            conditions.
          </p>
        </Reveal>
      </section>

      <section className="mx-auto mt-28 w-full max-w-7xl px-6 lg:px-12">
        <dl className="grid grid-cols-2 border-y border-line lg:grid-cols-4">
          {stats.map((stat, i) => (
            <Reveal
              key={stat.label}
              delay={0.08 * i}
              className={`flex flex-col-reverse py-10 pr-4 ${i % 2 ? "border-l border-line pl-6" : ""} ${
                i > 1 ? "border-t border-line lg:border-t-0" : ""
              } ${i === 2 ? "lg:border-l lg:pl-6" : ""}`}
            >
              <dt className="mt-3 text-xs font-semibold uppercase tracking-[0.2em] text-muted">{stat.label}</dt>
              <dd className={`text-[clamp(2.75rem,6vw,5rem)] text-accent ${heading}`}>{stat.value}</dd>
            </Reveal>
          ))}
        </dl>
      </section>

      <section className="mx-auto grid w-full max-w-7xl gap-10 px-6 py-28 lg:grid-cols-[1fr_2fr] lg:gap-16 lg:px-12">
        <div>
          <RevealLines as="p" className={label} lines={["Our Mission"]} />
          <RevealLines as="h2" delay={0.1} className={`mt-5 text-4xl sm:text-5xl ${heading}`} lines={["Why we", "exist"]} />
        </div>
        <div>
          <Reveal>
            <p className="text-2xl font-medium leading-snug tracking-tight sm:text-3xl">
              We believe in driving innovation through{" "}
              <span className="text-accent-deep">data science and digitalization</span> across process control,
              optimization, safety management, technology development, and scale-up.
            </p>
          </Reveal>
          <div className="mt-10 grid gap-6 text-[17px] leading-relaxed text-muted sm:grid-cols-2">
            <Reveal delay={0.1}>
              <p>
                Today, companies developing new processes and products rarely leverage the full potential of their lab
                and plant data. Aggressive deadlines and immediate operational KPIs often force teams into sub-optimal
                tradeoffs.
              </p>
            </Reveal>
            <Reveal delay={0.2}>
              <p>
                We partner with our clients to bridge that gap, transforming raw operating data into high-fidelity
                models and actionable intelligence. By integrating deep domain expertise with modern digital tools, we
                relieve the pressure of tight schedules and deliver reliable, optimized engineering solutions.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="border-t border-line bg-white">
        <div className="mx-auto max-w-7xl px-6 py-28 lg:px-12">
          <div className="grid gap-10 lg:grid-cols-2 lg:items-end">
            <div>
              <RevealLines as="p" className={label} lines={["Core Services"]} />
              <RevealLines
                as="h2"
                delay={0.1}
                className={`mt-5 text-[clamp(2.4rem,5vw,4.5rem)] ${heading}`}
                lines={[
                  "Four core",
                  <span key="capabilities" className="text-accent">
                    capabilities
                  </span>,
                ]}
              />
            </div>
            <Reveal delay={0.2}>
              <p className="text-muted">We serve the energy and chemical sectors, including:</p>
              <ul className="mt-4 flex flex-wrap gap-2">
                {sectors.map((sector) => (
                  <li key={sector} className="rounded-full border border-line bg-paper px-3.5 py-1.5 text-sm">
                    {sector}
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>

          <div className="mt-16 border-t border-line">
            {services.map((service, i) => (
              <Reveal key={service.title} delay={0.05}>
                <article className="group grid gap-4 border-b border-line py-10 transition-colors md:grid-cols-[80px_1fr_1.4fr] md:gap-10">
                  <span className="font-mono text-sm text-muted transition-colors group-hover:text-accent">
                    0{i + 1}
                  </span>
                  <h3 className="text-2xl font-semibold uppercase tracking-tight transition-transform duration-500 group-hover:translate-x-2 sm:text-3xl">
                    {service.title}
                  </h3>
                  <div>
                    <p className="leading-relaxed text-muted">{service.description}</p>
                    {service.tools && (
                      <ul className="mt-5 flex flex-wrap gap-2">
                        {service.tools.map((tool) => (
                          <li key={tool} className="rounded-full border border-line bg-paper px-3 py-1 font-mono text-xs">
                            {tool}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto grid w-full max-w-7xl gap-10 px-6 py-28 lg:grid-cols-[1fr_2fr] lg:gap-16 lg:px-12">
        <div>
          <RevealLines as="p" className={label} lines={["Specialities"]} />
          <RevealLines as="h2" delay={0.1} className={`mt-5 text-4xl sm:text-5xl ${heading}`} lines={["Where we", "go deep"]} />
        </div>
        <Reveal delay={0.15}>
          <ul className="flex flex-wrap gap-2.5">
            {specialities.map((item) => (
              <li
                key={item}
                className="flex items-center gap-2 rounded-full border border-line bg-white px-4 py-2 text-[15px] transition-colors hover:border-accent/50"
              >
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent" />
                {item}
              </li>
            ))}
          </ul>
        </Reveal>
      </section>

      <CtaBanner />
    </>
  );
}
