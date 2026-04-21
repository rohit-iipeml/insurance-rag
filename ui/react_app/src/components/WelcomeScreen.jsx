const PROMPTS = [
  "Is water damage from frozen pipes covered if vacant 65 days?",
  "Does endorsement NX-END-02 override Section 7.3?",
  "What is the hurricane deductible for Florida properties?",
  "What endorsements are attached to the John Smith policy?",
];

export default function WelcomeScreen({ onSubmit }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        padding: 40,
      }}
    >
      <div style={{ fontSize: 40, marginBottom: 16 }}>📋</div>

      <h1
        style={{
          fontSize: 26,
          fontWeight: 600,
          color: "var(--text-primary)",
          letterSpacing: "-0.5px",
          marginBottom: 8,
          textAlign: "center",
        }}
      >
        What would you like to know?
      </h1>

      <p
        style={{
          fontSize: 15,
          color: "var(--text-secondary)",
          marginBottom: 36,
          textAlign: "center",
        }}
      >
        Ask about coverage, exclusions, deductibles, or policy terms.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          width: "100%",
          maxWidth: 640,
        }}
      >
        {PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onSubmit(prompt)}
            style={{
              background: "#ffffff",
              border: "1px solid var(--border)",
              borderRadius: 10,
              padding: 14,
              fontSize: 13,
              fontWeight: 400,
              textAlign: "left",
              lineHeight: 1.4,
              cursor: "pointer",
              width: "100%",
              color: "var(--text-primary)",
              transition: "border-color 0.15s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#c0c0ba")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}
