type ConnectionErrorProps = {
  message: string;
};

/** Shown when the app cannot talk to its API — almost always a deploy setting. */
export default function ConnectionError({ message }: ConnectionErrorProps) {
  return (
    <section className="panel connection-error">
      <h2>Cannot reach the API</h2>
      <p className="connection-error-message">{message}</p>
      <p className="connection-error-hint">
        Open DevTools → Network and look at the <code>/api/v1/auth/config</code> request. If it goes
        to this site instead of the API host, <code>VITE_API_BASE</code> was not set when the
        frontend was built. If it goes to the API host but fails, check <code>CORS_ORIGINS</code> on
        the API.
      </p>
    </section>
  );
}
