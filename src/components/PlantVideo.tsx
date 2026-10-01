export default function PlantVideo({ className = "" }: { className?: string }) {
  return (
    <video
      className={`h-full w-full object-cover ${className}`}
      autoPlay
      muted
      loop
      playsInline
      preload="auto"
      poster="/videos/hero-poster.jpg"
      aria-hidden="true"
    >
      <source src="/videos/hero-mobile.mp4" type="video/mp4" media="(max-width: 767px)" />
      <source src="/videos/hero.mp4" type="video/mp4" />
    </video>
  );
}
