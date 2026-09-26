export default function MoviePoster({ src, fallback, alt, className }: { src: string; fallback: string; alt: string; className: string }) {
  return <img className={className} src={src} alt={alt} onError={(event) => {
    if (event.currentTarget.src !== fallback) event.currentTarget.src = fallback;
  }} />;
}
