# Washington Gas for Home Assistant (unofficial)

Imports Washington Gas bills from `wgl.opower.com` into Home Assistant's long-term
statistics, for the Energy dashboard. Not affiliated with or endorsed by Washington
Gas, WGL or Oracle. Best effort: it stops working if the site changes.

## What you get

- Gas usage and cost history, spread evenly over each bill's days
- Sensors: last bill usage, cost, average rate, start, end
- Several gas accounts under one login

## Limits

- **Bill data only.** The site served one read per bill on the account this was built
  with. Daily bars are averages, and totals near bill dates are approximate. Not live.
- Cost is what the portal reports. On that account it was the whole bill, fixed charges included.
- Tested with one Virginia account. Maryland, DC and multi-account logins are untested.
- Logins that ask for a verification code are not supported.

## Install

1. HACS → ⋮ → Custom repositories → `https://github.com/skontzias1/washington-gas-ha`, type Integration.
2. Install, then restart Home Assistant (2026.11 or newer).
3. Create a login at <https://wgl.opower.com>. Use a password you use nowhere else.
4. Settings → Devices & services → Add integration → **Washington Gas**.
5. Settings → Dashboards → Energy → Gas: choose the Washington Gas consumption and cost statistics.

## Units

The portal does not label its usage unit in the data used here. The default is therms.
Compare one bill with the site, and change the unit in the integration's options if needed.
Therms are converted to CCF with a factor you can set (default 1.04, an approximation; your
bill shows the real one). The factor does not affect cost.

## Privacy and safety

- Read-only. Connects only to `wgl.opower.com`, once a day and at startup or reload.
- Sign-in does not follow redirects. Requests stop after 60 seconds.
- Implausible data is rejected and never stored.
- Home Assistant stores the login unencrypted in its configuration, and backups include it.
- Bills are cached in `.storage` so history survives the portal dropping old bills.
- Diagnostics leave out the login, account IDs and bill amounts.
- You are responsible for following the [site's terms](https://wgl.opower.com/ei/x/terms-of-use).

## Remove

Remove the Energy source and the integration, then delete the `washington_gas:` statistics
under Developer tools → Statistics.

## Credits

Uses [opower](https://github.com/tronikos/opower) by tronikos. MIT license.
