# Frigate LPR Registry til Home Assistant

En lokal Home Assistant-integration, der lytter på Frigates MQTT-emne
`frigate/tracked_object_update`, registrerer nummerplader persistent og viser dem som
sensorer i Home Assistant. Standardkameraet er `rlgade`.

Data gemmes i Home Assistants egen `.storage` via `Store`; der kræves ingen ekstern
database. En genstart af Home Assistant bevarer plader, metadata og hele
observationshistorikken.

## Funktioner

- Én observation pr. unikt Frigate event-id (gentagne LPR-forsøg på samme bil tælles ikke flere gange).
- Første/seneste observation, samlet antal, antal forskellige dage, alle observationer og intervaller i sekunder.
- Dagstællere, seneste observationer, hyppigste, kendte og engangsbesøgende.
- Dynamisk sensor for hver plade; klik på sensoren viser statistik og de 50 seneste observationer/intervaller.
- Navngivning og kategori via handlingen `frigate_lpr.set_plate`.
- Forudindlæst: `EJ85963` og `EF41178` som `Egen bil` / `own`.

## Klassifikation

Klassifikationen gætter aldrig på ejerskab. Reglerne evalueres i denne rækkefølge:

| Klasse | Transparent regel |
|---|---|
| Egen | Brugeren har sat kategori `own` |
| Kendt lokal | Brugeren har sat kategori `known` eller et navn |
| Hyppig | Mindst 10 observationer fordelt over mindst 4 forskellige dage |
| Engangsbesøgende | Præcis 1 observation |
| Sjælden | Øvrige observerede plader |

Grænserne for **Hyppig** kan ændres under integrationens indstillinger. Ændringen
klassificerer de samme observerede data på ny; den ændrer ikke historikken.

## Installation

1. Kopiér `custom_components/frigate_lpr` til samme placering under Home Assistants konfigurationsmappe.
2. Genstart Home Assistant.
3. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration** og vælg **Frigate LPR Registry**.
4. Behold emnet `frigate/tracked_object_update`, og angiv kamera `rlgade`.
5. Kontrollér, at Home Assistants MQTT-integration er tilsluttet samme broker som Frigate.

Frigate sender LPR som `type: lpr` med felterne `id`, `plate`, `camera`, `score` og
`timestamp`. Andre meddelelsestyper og andre kameraer ignoreres.

## Dashboard

Importér råkonfigurationen fra
[`dashboard/frigate-lpr-dashboard.yaml`](dashboard/frigate-lpr-dashboard.yaml) som et
nyt YAML-dashboard. Home Assistant kan give entiteter et andet id, især hvis navnene
allerede findes; ret derfor de syv oversigts-id'er i filen efter behov.

Det sidste kort finder automatisk alle pladesensorer og gør hver række klikbar. Det
bruger [auto-entities](https://github.com/thomasloven/lovelace-auto-entities), som kan
installeres via HACS. Resten af dashboardet bruger kun indbyggede Home Assistant-kort.
Uden auto-entities kan pladesensorerne tilføjes manuelt til et almindeligt
**Entiteter**-kort; klik giver den samme detaljevisning.

## Tilføj eller opdater en kendt plade

Kør under **Udviklerværktøjer → Handlinger**:

```yaml
action: frigate_lpr.set_plate
data:
  plate: AB12345
  name: Naboens bil
  category: known
```

Brug `category: own` kun for en plade, som brugeren selv har valgt at betegne som
egen. Handlingen `frigate_lpr.remove_plate_metadata` fjerner navn og kategori, men
bevarer observationerne.

## Automatisering

Integrationen udsender eventet `frigate_lpr_new_plate` første gang en ukendt plade
ses. Et eksempel findes i [`examples/automations.yaml`](examples/automations.yaml).

## Udvikling og test

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall custom_components/frigate_lpr
```

Testene dækker normalisering, deduplikering, statistik, persistens-roundtrip og alle
klassifikationsgrene. Integrationens MQTT- og entity-lag kræver en rigtig Home
Assistant-installation til end-to-end-test.

## Databeskyttelse og drift

Nummerplader kan være personoplysninger. Begræns adgang til Home Assistant, vælg en
passende opbevaringspraksis, og følg gældende regler. Denne version gemmer hele
historikken; lagerforbruget vokser derfor over tid. Home Assistants backup inkluderer
`.storage` og dermed registeret. Hele historikken ligger i lageret; sensorattributterne
viser de 50 seneste poster for ikke at overbelaste Home Assistants state-database.

## MQTT-testpayload

```json
{
  "type": "lpr",
  "id": "test-vehicle-1",
  "name": null,
  "plate": "AB12345",
  "score": 0.95,
  "camera": "rlgade",
  "timestamp": 1790438400.0,
  "plate_box": [917, 487, 1029, 529]
}
```
