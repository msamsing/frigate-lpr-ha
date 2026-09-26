# Frigate LPR Registry til Home Assistant

En lokal Home Assistant-integration, der lytter på Frigates MQTT-emne
`frigate/tracked_object_update`, registrerer nummerplader persistent og viser dem som
sensorer i Home Assistant. MQTT-emne og et valgfrit kamerafilter vælges i opsætningsdialogen.

Data gemmes i Home Assistants egen `.storage` via `Store`; der kræves ingen ekstern
database. En genstart af Home Assistant bevarer plader, metadata og hele
observationshistorikken.

## Funktioner

- Én observation pr. unikt Frigate event-id (gentagne LPR-forsøg på samme bil tælles ikke flere gange).
- Første/seneste observation, samlet antal, antal forskellige dage, alle observationer og intervaller i sekunder.
- Dagstællere, seneste observationer, hyppigste, kendte og engangsbesøgende.
- Dynamisk sensor for hver plade; klik på sensoren viser statistik og de 50 seneste observationer/intervaller.
- Navngivning og kategori gennem integrationens UI eller handlingen `frigate_lpr.set_plate`.
- Egne og andre kendte plader kan oprettes efter installationen.
- Medfølgende Lovelace-kort med overblik og klikbar pladehistorik uden ekstra frontend-afhængigheder.

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

### HACS

1. Åbn HACS, vælg **Custom repositories**, og tilføj `https://github.com/msamsing/frigate-lpr-ha` som typen **Integration**.
2. Installér **Frigate LPR Registry** og genstart Home Assistant.
3. Tilføj integrationen fra **Indstillinger → Enheder og tjenester**. Resten konfigureres i UI'et.

### Manuel installation

1. Kopiér `custom_components/frigate_lpr` til samme placering under Home Assistants konfigurationsmappe.
2. Genstart Home Assistant.
3. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration** og vælg **Frigate LPR Registry**.
4. Behold standardemnet `frigate/tracked_object_update`, eller ret det hvis Frigate bruger et andet MQTT-præfiks.
5. Angiv eventuelt et kameranavn. Et tomt felt accepterer observationer fra alle kameraer.
6. Kontrollér, at Home Assistants MQTT-integration er tilsluttet samme broker som Frigate.

MQTT-emne og kamerafilter kan senere ændres fra integrationens **Konfigurer**-dialog.
Frekvensgrænser og kendte plader håndteres under integrationens **Indstillinger**.
Ingen YAML er nødvendig for selve integrationen.

Frigate sender LPR som `type: lpr` med felterne `id`, `plate`, `camera`, `score` og
`timestamp`. Andre meddelelsestyper ignoreres. Kameraer filtreres kun, hvis brugeren vælger det.

## Dashboard

Lovelace-kortet følger med integrationen og registreres automatisk som en frontend-resource.
Efter genstart kan det tilføjes fra dashboardets kortvælger som **Frigate LPR Registry**.
Det kræver ingen andre custom cards.

Minimal YAML-konfiguration:

```yaml
type: custom:frigate-lpr-card
title: Nummerpladeregister
```

Et komplet dashboardeksempel findes i
[`dashboard/frigate-lpr-dashboard.yaml`](dashboard/frigate-lpr-dashboard.yaml).
Kortet finder integrationens entiteter via attributter og er derfor uafhængigt af
kamera- og entity-navne. Klik på en plade åbner dens statistik, klassifikation,
intervaller og seneste observationshistorik.

Hvis Home Assistant bruger Lovelace resources i YAML-tilstand, kan integrationen ikke
ændre ressourcefilen automatisk. Tilføj da dette under dashboardets `resources` og
genstart:

```yaml
- url: /frigate_lpr_static/frigate-lpr-card.js
  type: module
```

## Tilføj eller opdater en kendt plade

Åbn integrationen, vælg **Indstillinger**, og vælg **Tilføj eller opdater kendt
nummerplade**. Samme funktion kan bruges i en automatisering via handlingen nedenfor.

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
  "camera": "camera_name",
  "timestamp": 1790438400.0,
  "plate_box": [917, 487, 1029, 529]
}
```
