type ReactorSpec = {
  reaction: string;
  D_m: number;
  L_m: number;
  h_heat_W_m2K: number;
  epsilon: number;
  dp_m: number;
};

function fmt(n: number | null | undefined, digits = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export default function ReactorGeometry({
  reactor,
  T_heat,
  note = "constant for every operating point",
}: {
  reactor: ReactorSpec;
  T_heat: number;
  note?: string;
}) {
  const specs = [
    { label: "Tube diameter", value: fmt(reactor.D_m, 2), unit: "m" },
    { label: "Bed length", value: fmt(reactor.L_m, 1), unit: "m" },
    { label: "Bed voidage", value: fmt(reactor.epsilon, 2), unit: "" },
    { label: "Particle size", value: fmt(reactor.dp_m * 1000, 1), unit: "mm" },
    { label: "Wall h", value: fmt(reactor.h_heat_W_m2K, 0), unit: "W/m²·K" },
    { label: "Heat media", value: fmt(T_heat, 0), unit: "°C" },
  ];

  return (
    <div className="rx-geometry">
      <div className="rx-geometry-head">
        <div>
          <p className="rx-geometry-title">Reactor geometry</p>
          <p className="rx-geometry-note">{note}</p>
        </div>
        <p className="rx-geometry-reaction" title="Stoichiometry">
          {reactor.reaction}
        </p>
      </div>

      <div className="rx-geometry-body">
        <svg
          className="rx-geometry-sketch"
          viewBox="0 0 280 120"
          role="img"
          aria-label={`Packed tube, diameter ${fmt(reactor.D_m, 2)} m, length ${fmt(reactor.L_m, 1)} m`}
        >
          {/* Jacket */}
          <rect x="28" y="28" width="210" height="52" rx="8" className="rx-geo-jacket" />
          {/* Tube / bed */}
          <rect x="36" y="38" width="194" height="32" rx="4" className="rx-geo-tube" />
          {/* Pellets hint */}
          {[48, 72, 96, 120, 144, 168, 192, 216].map((x) => (
            <circle key={x} cx={x} cy="54" r="3.2" className="rx-geo-pellet" />
          ))}
          {/* Length dimension */}
          <line x1="36" y1="98" x2="230" y2="98" className="rx-geo-dim" />
          <line x1="36" y1="94" x2="36" y2="102" className="rx-geo-dim" />
          <line x1="230" y1="94" x2="230" y2="102" className="rx-geo-dim" />
          <text x="133" y="114" textAnchor="middle" className="rx-geo-label">
            L = {fmt(reactor.L_m, 1)} m
          </text>
          {/* Diameter dimension */}
          <line x1="248" y1="38" x2="248" y2="70" className="rx-geo-dim" />
          <line x1="244" y1="38" x2="252" y2="38" className="rx-geo-dim" />
          <line x1="244" y1="70" x2="252" y2="70" className="rx-geo-dim" />
          <text x="262" y="58" textAnchor="start" className="rx-geo-label">
            D
          </text>
          <text x="8" y="56" textAnchor="middle" className="rx-geo-label" transform="rotate(-90 8 56)">
            feed →
          </text>
        </svg>

        <dl className="rx-geometry-specs">
          {specs.map((s) => (
            <div key={s.label}>
              <dt>{s.label}</dt>
              <dd>
                {s.value}
                {s.unit ? <small> {s.unit}</small> : null}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
