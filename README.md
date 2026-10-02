# Frigate LPR Registry til Home Assistant

En lokal Home Assistant-integration, der lytter på Frigates MQTT-emne
`frigate/tracked_object_update`, registrerer nummerplader persistent og viser dem som
sensorer i Home Assistant. MQTT-emne og et valgfrit kamerafilter vælges i opsætningsdialogen.

Integrationen og det tilhørende Lovelace-kort er blandt andet tænkt til overblik over
et privat parkeringsareal ved en boligforening, et privat fællesområde eller lignende.
Brugen skal altid ske med passende adgangskontrol, skiltning og i overensstemmelse med
gældende regler om kameraovervågning og behandling af personoplysninger.

Data gemmes i Home Assistants egen `.storage` via `Store`; der kræves ingen ekstern
database. En genstart af Home Assistant bevarer plader, metadata og hele
observationshistorikken.

## Funktioner

- Én observation pr. unikt Frigate event-id (gentagne LPR-forsøg på samme bil tælles ikke flere gange).
- Første/seneste observation, samlet antal, antal forskellige dage, alle observationer og intervaller i sekunder.
- Dagstællere, seneste observationer, hyppigste, kendte og engangsbesøgende.
- Dynamisk sensor for hver plade; klik på sensoren viser statistik og de 50 seneste observationer/intervaller.
- Navngivning og kategorierne Egen, Kendt, Ukendt og Uønsket gennem kortet eller handlingen `frigate_lpr.set_plate`.
- Egne og andre kendte plader kan oprettes efter installationen.
- Medfølgende Lovelace-kort, som kan vælges og konfigureres direkte i dashboard-editoren.
- Forklarlig mønsteranalyse med tidsklynger, ugedage, besøgsrytme, udvikling og sikkerhedsgrad.
- Valgfrit permanent snapshot af den seneste passage på hver køretøjssag.
- Redigering og sletning af enkelte passager med automatisk genberegning af statistikken.
- Køretøjssager kan ignoreres i oversigter og samlet trafikstatistik uden at blive slettet.
- Særskilt trafikvisning med time-, ugedags- og kategorifordeling.
- Valgfrit MotorAPI-opslag af mærke, model og andre grunddata for helt nye, ukendte plader.
- Plader, som brugeren har navngivet eller markeret som Egen, Kendt eller Uønsket, sendes aldrig automatisk til MotorAPI.

## Klassifikation

Klassifikationen gætter aldrig på ejerskab. Reglerne evalueres i denne rækkefølge:

| Klasse | Transparent regel |
|---|---|
| Egen | Brugeren har sat kategori `own` |
| Kendt lokal | Brugeren har sat kategori `known` eller har navngivet en plade uden en anden udtrykkelig kategori |
| Ukendt | Brugeren har sat den neutrale kategori `unknown` |
| Uønsket | Brugeren har udtrykkeligt sat kategori `unwanted` |
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

### Valgfrit opslag af køretøjsdata

Under **Indstillinger → Køretøjsopslag via MotorAPI** kan opslag aktiveres med en
API-nøgle fra [motorapi.dk](https://www.motorapi.dk/). Når en helt ny og ukendt
nummerplade observeres første gang, hentes og gemmes køretøjets stamdata lokalt på
køretøjssagen. De vigtigste felter vises i sensoren og Lovelace-kortet.

Af hensyn til privatliv og API-forbrug gælder følgende:

- En plade, som allerede har et brugerdefineret navn eller kategorien **Egen**,
  **Kendt lokal** eller **Uønsket**, sendes aldrig automatisk til MotorAPI.
- Kun plader, der observeres første gang efter funktionen er aktiveret, slås op;
  eksisterende historik sendes ikke bagudrettet.
- Ethvert opslag markeres persistent som forsøgt, også hvis pladen ikke findes eller
  API'et svarer med en fejl. Senere observationer medfører derfor ikke nye API-kald.
- Hele datasættet, som MotorAPIs køretøjs-endpoint returnerer, gemmes persistent lokalt
  i Home Assistant på sagen. Det kan derfor også indeholde VIN/stelnummer og andre
  oplysninger, som ikke vises direkte i kortets kompakte oversigt.
- På en gemt sag findes knappen **Hent stamdata fra MotorAPI**. Den er kun aktiv, når
  API'et er konfigureret. Knappen er et udtrykkeligt manuelt opslag og kan derfor også
  bruges på en sag markeret **Egen** eller **Kendt lokal**; pladen sendes kun, når
  brugeren selv trykker på knappen.

Hvis en plade skal beskyttes mod opslag, skal den oprettes som **Egen** eller **Kendt
lokal**, før den observeres første gang. Når en ukendt plade først er sendt til API'et,
kan det tidligere netværkskald naturligvis ikke trækkes tilbage.

### Valgfrit passagebillede fra en image-entitet

Under **Indstillinger → Snapshot fra billedentitet** kan brugeren vælge den
Home Assistant-`image`-entitet, som Frigate opdaterer med det aktuelle
køretøjsbillede, eksempelvis `image.indkoersel_car`. Der kræves ingen Frigate-adresse,
API-token eller særskilt SSL-konfiguration.

Ved hver LPR-observation venter integrationen kort på, at billedentiteten opdateres,
og kopierer derefter billedet til Home Assistants
`.storage/frigate_lpr_snapshots`. Der gemmes kun det seneste billede pr.
nummerplade. Den lokale kopi ændres derfor ikke, når image-entiteten senere viser
en anden bil; den erstattes først ved næste passage for samme nummerplade. Billedet
udleveres kun gennem et autentificeret Home Assistant-endpoint og kan åbnes i stor
størrelse fra køretøjssagen.

Knappen **Slet billede** på køretøjssagen fjerner kun den lokale billedfil og
billedreferencen. Passagehistorik, statistik og stamdata bevares. Et nyt billede
gemmes først, når den samme nummerplade registreres ved en senere passage. Det er
især nyttigt, hvis to næsten samtidige passager har fået knyttet det samme billede
til begge sager. En igangværende billedhentning annulleres logisk, så den ikke kan
genskabe billedet umiddelbart efter sletningen.

Frigate sender LPR som `type: lpr` med felterne `id`, `plate`, `camera`, `score` og
`timestamp`. Andre meddelelsestyper ignoreres. Kameraer filtreres kun, hvis brugeren vælger det.

## Dashboard

Integrationen indlæser automatisk det medfølgende Lovelace-kort. Den opretter ikke
et dashboard og tilføjer ikke noget til sidepanelet.

Sådan bruges kortet:

1. Åbn det dashboard, hvor overblikket skal vises, og vælg **Rediger dashboard**.
2. Vælg **Tilføj kort** og søg efter **Frigate LPR Registry**.
3. Konfigurer titel, antal viste plader, nøgletal og detaljevisning i
   den grafiske editor, og vælg **Gem**.

Der skal ikke kopieres YAML eller oprettes en Lovelace-resource manuelt. Integrationen
registrerer selv kortets modul i Home Assistants Lovelace-resource-lager. Kortet finder
automatisk integrationens entiteter. På brede kort vises en søgbar og sorterbar
køretøjsliste, den valgte køretøjssag med statistik og grafer samt en fast kolonne
med de seneste passager. På telefon bruges fanerne **Seneste**, **Køretøjer**,
**Detaljer** og **Trafik**, så ingen desktop-tabel presses sammen eller kræver
vandret rulning.

Kategori og bemærkning kan ændres direkte i detaljevisningen. Den fulde editor kan
oprette og redigere køretøjssager med navn/relation og stamdata. Graferne viser
tidspunkt på døgnet og passager i den seneste uge; mønsterteksten er alene baseret
på observationerne. Den viser en primær konklusion, op til to sekundære fund,
sikkerhedsgrad og de konkrete tal bag resultatet. Analysen kan genkende tidsklynger,
hverdags-/weekendtendenser, ugentlig rytme, flere daglige passager og udvikling mellem
30-dages perioder uden at gætte på ejer eller tilhørsforhold. Kortets layout reagerer på sin egen bredde via container queries
og følger Home Assistants aktive lyse eller mørke tema. Oplysningerne gemmes af
integrationen i Home Assistants persistente lager.

De seneste 50 passager på den valgte køretøjssag kan redigeres eller slettes direkte.
Ved en rettelse genberegnes første/seneste observation, intervaller, antal dage,
mønsteranalyse og den samlede trafikstatistik. Sletning er permanent, mens resten af
køretøjssagen bevares. Markeringen **Ignorér i oversigter** skjuler sagen fra seneste
passager og trafikstatistik; den kan stadig findes under filteret **Ignorerede sager**.

Visningen **Trafikstatistik** viser passager pr. time og ugedag, de seneste 7 og 30
dage, gennemsnit pr. dag, travleste tidspunkt samt andelen af kendte inklusive egne,
ukendte og uønskede passager. Tallene beskriver kun nummerplader, som Frigate faktisk
har aflæst, og skal derfor ikke forstås som en komplet trafikmåling.

Ved opgradering fra 1.3.1 fjernes det selvstændige **Nummerplader**-dashboard, som
den version oprettede, automatisk.

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
egen. De øvrige værdier er `known`, `unknown` og `unwanted`. Handlingen
`frigate_lpr.remove_plate_metadata` fjerner navn og kategori, men bevarer observationerne.

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
