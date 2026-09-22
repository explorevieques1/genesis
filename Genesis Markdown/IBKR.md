The thing nobody tells you about IBKR's API

IBKR doesn't have a normal API. There's no api.ibkr.com you send a request to with a key.

Instead, IBKR makes you run their desktop Java application — TWS or the lighter IB Gateway — on your own machine, logged in with your username and password. That desktop app is the real client of IBKR's servers. Your Python code then talks to the app over a local TCP socket on port 4001/4002. Your code is a client of a GUI program that happens to be sitting on your desk.

That's the whole awkwardness, and every problem flows from it:

- It's a GUI app. It expects a screen, a window, a mouse.
- It needs a human to log in. Username, password, dialogs, sometimes 2FA.
- IBKR forces it to restart roughly every 24 hours. Auth tokens expire. Don't restart it and it logs itself out.
- When it dies, your data just stops — often without your code noticing, because the socket goes quiet rather than erroring.

Now hold that next to what Genesis is: an always-on daemon with a market calendar, running an overnight pass at 16:05, 17:00 and 06:45. "A desktop app that needs someone to type a password and restarts itself every night" is a direct contradiction of that.

What the repo does

gnzsnz/ib-gateway-docker packages IB Gateway into a Docker container and solves each of those:

- Gives it a fake screen. Runs a virtual X display, so a GUI app runs on a machine with no monitor, no desktop, no logged-in user.
- Logs in for you. It bundles IBC, a tool that puppets the Gateway's interface — types your credentials into the login box, clicks through the dialogs, dismisses the nags, answers the restart prompt.
- Handles the daily restart on a schedule you set, so a forced outage becomes a known event in a window you chose instead of a mystery 3am failure.
- Exposes the socket as a normal port, so your adapter just connects to localhost:4002 like any service.
- Optional VNC, so when something is wrong you can actually look at the invisible screen and see which dialog it's stuck on. You will want this at least once.

Net effect: it turns a desktop application that assumes a human into a service that starts with docker compose up and stays up. IBKR starts behaving like the API it isn't.

Why it matters for Genesis specifically

Here's the part that connects to your own architecture, and it's the real argument.

Your Market Data Sources.md explains why TradingView is stuck at tier 2, and one of the three reasons is: "it requires a GUI session, so it is unavailable to the 3am market-closed loop."

IBKR has exactly the same defect. It's also a GUI app requiring a session. Left alone, IBKR would be tier 2 for precisely the reason TradingView is — and then you'd still have no tier-1 source, and Pre-Trade Risk Engine would still have nothing to read in Phase 7.

The Docker gateway is what removes that defect. It's not a convenience or a deployment preference. It is the thing that makes IBKR eligible to be tier 1 at all. That's worth writing into Market Data Sources.md when you record the tier-1 decision, because otherwise it reads like an arbitrary infrastructure choice, and six months from now someone — possibly you — decides it'd be simpler to just run Gateway on the desktop, and quietly reintroduces the exact failure the tier system exists to prevent.

Three smaller wins that fit your existing patterns: the config lives in a compose file in git while credentials stay in .env (your layered loader already works this way); the container restarts on failure under Docker's supervision, mirroring the daemon's own crash → backoff → degraded model; and it runs identically on your Arch box tonight and on a VPS later with no changes.

Be honest about the costs

Your IBKR password sits in a file that IBC reads. That's real and there's no way around it — the design requires the credentials because the design requires a login. Mitigate: lock the file permissions, never commit it, run paper-only until Phase 7, and keep Read-Only API on so a compromised connection still can't trade.

2FA is the friction point. IBKR pushes two-factor to their mobile app, which is hostile to headless operation. Paper accounts are generally smoother here, which is another reason to develop against paper for a long time. For live headless, plan on it needing attention — it's the single most likely thing to interrupt an otherwise unattended system, and it's better to find that out now than at 6am when the brief didn't run.

It's a puppet, not an API. Underneath, something is still clicking buttons in a Java app. When IBKR ships a new dialog, IBC sometimes needs an update. Pin your versions, expect occasional maintenance, and treat "the gateway didn't come up" as an expected failure mode your watchdog handles — not an exception.

That last point is the honest summary of the whole approach: it's a well-maintained, widely-used workaround for a broker that never built a real API. It works reliably. It is not elegant. Given that IBKR is otherwise the best value in the market by a wide margin, it's a trade worth making — but build the staleness guard knowing this is the layer most likely to fail.

gnzsnz/ib-gateway-docker (https://github.com/gnzsnz/ib-gateway-docker)