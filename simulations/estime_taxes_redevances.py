import configparser
import re
import time

import numpy
import pandas  # noqa: I201

from openfisca_core.simulation_builder import SimulationBuilder  # noqa: I100

from openfisca_france_fiscalite_miniere import CountryTaxBenefitSystem as FranceFiscaliteMiniereTaxBenefitSystem  # noqa: E501
from openfisca_france_fiscalite_miniere.variables.taxes import CategorieEnum

from simulations.drfip import (
    generate_matrice_annexe_drfip_guyane,
    generate_matrice_drfip_guyane
    )


# ADAPT INPUT DATA

def get_activites_data(csv_activites):
    activite_par_titre: pandas.DataFrame = pandas.read_csv(csv_activites)
    activites_data = activite_par_titre[
        [
            'titre_id', 'annee', 'periode', 'type',
            'renseignements_orBrut', 'renseignements_orNet',
            'renseignements_environnement',
            'complement_texte'
            ]
        ]

    print(len(activites_data), "ACTIVITES")
    print(activites_data[['titre_id', 'annee']].head())

    return activites_data


def get_titres_data(csv_titres):
    communes_par_titre: pandas.DataFrame = pandas.read_csv(csv_titres)
    titres_data = communes_par_titre[
        [
            'id', 'domaine', 'substances',
            'communes', 'departements', 'administrations_noms',
            'titulaires_noms', 'titulaires_adresses', 'titulaires_categorie',
            'amodiataires_noms', 'amodiataires_adresses', 'amodiataires_categorie'
            ]
        ]

    print(len(titres_data), "TITRES")
    print(titres_data[['id', 'communes']].head())

    return titres_data


def get_entreprises_data(csv_entreprises):
    entreprises: pandas.DataFrame = pandas.read_csv(csv_entreprises)
    entreprises_data = entreprises[
        ['nom', 'siren']
        ]

    print(len(entreprises_data), "ENTREPRISES")
    print(entreprises_data.head())

    return entreprises_data


def get_activites_annee(activite_par_titre, annee):
    # TODO fix incohérence :
    # annee en chaîne de caractères pour les tests mais en int pour la prod
    filtre_annee_activite = activite_par_titre['annee'] == annee
    activites_data = activite_par_titre[filtre_annee_activite]
    return activites_data


def get_titres_annee(communes_par_titre, activites_data):
    '''
    Sélectionne les titres de l'année de calcul parmi les données
    de l'export des titres par communes.
    L'année étant présente dans un autre export, celui des activités,
    emploie la liste des identifiants de titres de 'activites_data'
    déjà filtré à l'année choisie pour la sélection dans l'export
    des titres par communes.

    Ceci sachant que 'titre_id' des exports d'activités (csv_activites)
    = 'id' des exports de titres (csv_titres)
    '''
    # selection des titres pour lesquels nous avons des activités
    titres_ids = activites_data.titre_id
    filtre_titres = communes_par_titre['id'].isin(titres_ids.tolist())
    titres_data = communes_par_titre[filtre_titres]
    return titres_data


def get_simulation_full_data(titres_data, activites_data):
    # 'titre_id' des exports d'activités (csv_activites) = 'id'
    # des exports de titres (csv_titres)
    full_data: pandas.DataFrame = pandas.merge(
        activites_data, titres_data, left_on='titre_id', right_on='id'
        ).drop(columns=['id'])  # on supprime la colonne 'id' en doublon avec 'titre_id'

    print(len(full_data), "SIMULATION DATA")
    # print(full_data[['titre_id', 'periode', 'communes']].head())

    # full_data.to_csv(f'full_data_{time.strftime("%Y%m%d-%H%M%S")}.csv', index=False)
    assert not full_data.empty
    return full_data


def separe_commune_surface(commune_surface):
    '''Transforme 'Commune1 (0.123)' en 'Commune1', 0.123'''
    match = re.match("(.*)\((.*)\)", commune_surface)  # noqa: W605
    return match.group(1).strip(), match.group(2).strip()


def dispatch_titres_multicommunes(data):
    # on éclate les titres multicommunaux en plusieurs occurrences du _même_ titre_id
    # chaque occurrence cible une commune (avec sa surface)
    # 'Commune1 (0.123);Commune2 (4.567)'
    data['communes'] = data.communes.str.split(pat=';')
    une_commune_par_titre = data.explode(
        "communes",
        ignore_index=True  # ! pandas v 1.1.0+
        ).dropna(subset=['titre_id'])  # dropping NaN values from exploded empty lists
    # print(une_commune_par_titre[
    #   ['titre_id', 'periode', 'communes', 'renseignements_orNet']
    # ])

    titres_names, titres_occurrences = numpy.unique(
        une_commune_par_titre.titre_id,
        return_counts=True
        )
    une_commune_par_titre.assign(Name='surface_communale')
    une_commune_par_titre.assign(Name='surface_totale')
    une_commune_par_titre.assign(Name='nom_commune')  # sans surface
    une_commune_par_titre.assign(Name='commune_exploitation_principale')

    # on répertorie les groupes de nouveaux titres unicommunaux créés ici
    # à partir d'un titre multicommunal pour le futur
    # calcul de surface totale par titre :
    titres_multicommunaux = {}

    for index, occurrence_titre in enumerate(titres_occurrences):
        titre_courant = titres_names[index]
        data_titre_courant = une_commune_par_titre[
            une_commune_par_titre.titre_id == titre_courant
            ]

        dispatched_titres = []
        if occurrence_titre > 1:  # titre sur plusieurs communes
            for j, row in data_titre_courant.iterrows():
                titre_unicommunal = titre_courant
                # print("👹👹 ", titre_courant, row.communes)
                commune, surface = separe_commune_surface(row.communes)

                # titre 'toto' devient 'toto+nom_commune_sans_surface'
                titre_unicommunal += "+" + commune
                une_commune_par_titre.loc[j, 'titre_id'] = titre_unicommunal
                une_commune_par_titre.loc[j, 'nom_commune'] = commune
                une_commune_par_titre.loc[j, 'surface_communale'] = float(surface)
                dispatched_titres.append(titre_unicommunal)
            titres_multicommunaux[titre_courant] = dispatched_titres
        else:
            # print("👹   ", titre_courant, data_titre_courant.communes.values)
            commune, surface = separe_commune_surface(
                str(data_titre_courant.communes.values[0])
                )
            filtre_titre = une_commune_par_titre.titre_id == titre_courant
            une_commune_par_titre.loc[
                filtre_titre, 'surface_communale'
                ] = float(surface)
            une_commune_par_titre.loc[filtre_titre, 'surface_totale'] = float(surface)
            une_commune_par_titre.loc[filtre_titre, 'nom_commune'] = commune
            une_commune_par_titre.loc[
                filtre_titre, 'commune_exploitation_principale'
                ] = commune

    # on calcule les surfaces totales des titres multicommunaux éclatés
    # print("***", titres_multicommunaux)
    for titre_multicommunal, titres_dispatched in titres_multicommunaux.items():  # noqa: B007, E501
        filtre_titres_dispatched = une_commune_par_titre.titre_id.isin(
            titres_dispatched
            )
        titres_dispatched_rows = une_commune_par_titre[filtre_titres_dispatched]
        surface_totale = titres_dispatched_rows.surface_communale.sum()

        surface_max = titres_dispatched_rows.surface_communale.max()
        commune_surface_max = titres_dispatched_rows['nom_commune'][
            titres_dispatched_rows.surface_communale == surface_max
            ].values[0]
        # print(titres_dispatched_rows[['titre_id', 'surface_communale']])
        # print(titre_multicommunal, "MAX", surface_max)
        # print(titre_multicommunal, " >>> ", commune_surface_max)
        une_commune_par_titre.loc[
            filtre_titres_dispatched, 'surface_totale'
            ] = surface_totale
        une_commune_par_titre.loc[
            filtre_titres_dispatched, 'commune_exploitation_principale'
            ] = commune_surface_max
        # print("👹👹👹 ", titre_multicommunal, titres_dispatched, surface_totale)

    return une_commune_par_titre


def convertit_grammes_a_kilo(data, colonne):
    data[colonne] = data[colonne].astype(float).divide(1000)
    return data


def clean_data(data):
    '''
    Parmi les colonnes qui nous intéressent, filtrer et adapter le format des valeurs.
    '''
    quantites_chiffrees = data
    quantites_chiffrees.loc[
        'renseignements_orNet'
        ] = data.renseignements_orNet.fillna(0.)
    quantites_chiffrees = convertit_grammes_a_kilo(
        quantites_chiffrees, 'renseignements_orNet'
        )
    # print("👹👹👹 ", quantites_chiffrees.renseignements_orNet.head())

    print(len(quantites_chiffrees), "CLEANED DATA")
    # print(quantites_chiffrees[
    #   ['titre_id', 'periode', 'communes', 'renseignements_orNet']
    # ].head())

    # on éclate les titres multicommunaux en une ligne par titre+commune unique
    # attention : on refait l'index du dataframe pour distinguer les lignes résultat.
    une_commune_par_titre = dispatch_titres_multicommunes(quantites_chiffrees)

    return une_commune_par_titre


def get_categories_entreprises(data):
    # pour l'or, data['amodiataires_categorie'] entièrement à NaN
    # print("🍒    ", data[data['amodiataires_categorie'].notnull()])
    assert data['amodiataires_categorie'].isna().all(), data[
        data['amodiataires_categorie'].notnull()
        ][['titre_id', 'amodiataires_categorie']]
    # on choisit donc 'titulaires_categorie'
    # pour l'or, data['titulaires_categorie'] à ETI, GE ou PME
    categories = data['titulaires_categorie'].apply(
        lambda categorie: CategorieEnum.pme if "PME" else CategorieEnum.autre
        )
    return categories.to_numpy()


def add_entreprises_data(data, entreprises_data):
    noms_entreprises = data.amodiataires_noms.where(
        data.amodiataires_noms.notnull(),
        other = data.titulaires_noms
        )
    data['nom_entreprise'] = noms_entreprises

    adresses_entreprises = data.amodiataires_adresses.where(
        data.amodiataires_noms == data.nom_entreprise,
        other = data.titulaires_adresses
        )
    data['adresse_entreprise'] = adresses_entreprises
    data['categorie_entreprise'] = data['titulaires_categorie']

    merged_data = data.merge(
        entreprises_data,
        how='left',
        left_on='nom_entreprise',
        right_on='nom'
        ).drop(columns=['nom'])

    return merged_data


def select_reports(data: pandas.DataFrame, type: str) -> pandas.DataFrame:  # noqa: A002
    selected_reports = data[data.type == type]
    print(len(selected_reports), "SELECTED REPORTS ", type)
    return selected_reports


def calculate_renseignements_environnement_annuels(
        titres_ids, rapports_trimestriels
        ) -> list:
    '''
    Somme les investissements par titre d'après les montants
    de "renseignements_environnement" des rapports trimestriels d'exploitation
    de chaque titre.
    @return Une liste des investissements annuels calculés
    selon l'ordre des "titres_ids" fournis en entrée.
    '''
    renseignements_environnement_annuels = []
    for titre_id in titres_ids:
        renseignements_trimestriels_titre: pandas.DataFrame = rapports_trimestriels[
            rapports_trimestriels.titre_id == titre_id
            ]
        # print(renseignements_trimestriels_titre[
        #   ['titre_id', 'periode', 'renseignements_environnement']
        # ])
        assert renseignements_trimestriels_titre.periode.isin(
            ['1er trimestre', '2e trimestre', '3e trimestre', '4e trimestre']
            ).all()
        renseignements_annuels_titre = renseignements_trimestriels_titre.renseignements_environnement.sum()  # noqa: E501
        renseignements_environnement_annuels.append(renseignements_annuels_titre)
    return renseignements_environnement_annuels


# SIMULATION


def build_simulation(tax_benefit_system, period, titres_ids, communes_ids):
    simulation_builder = SimulationBuilder()
    simulation_builder.create_entities(tax_benefit_system)
    simulation_builder.declare_person_entity(
        'societe',
        titres_ids
        )  # titres sans doublons via renommage multicommunes

    # associer les communes aux titres :
    commune_instance = simulation_builder.declare_entity('commune', communes_ids)
    # un id par titre existant dans l'ordre de titres_ids :
    titres_des_communes = communes_ids
    # role de chaque titre dans la commune = societe :
    titres_communes_roles = ['societe'] * len(titres_des_communes)
    simulation_builder.join_with_persons(
        commune_instance,
        titres_des_communes,
        roles = titres_communes_roles
        )

    return simulation_builder.build(tax_benefit_system)


if __name__ == "__main__":

    # CONFIGURATION
    config = configparser.ConfigParser()
    config.read("config.ini")

    data_period = int(config['SIMULATIONS']['periode'])

    # Camino, export Titres miniers et autorisations :
    csv_titres = config['SIMULATIONS']['titres']
    # Camino, export Activités
    # substance "or", tout type de titre, tout statut de titre
    # tout type de rapport, statut "déposé" uniquement
    # année N-1
    csv_activites = config['SIMULATIONS']['activites']

    csv_entreprises = config['SIMULATIONS']['entreprises']

    # ADAPT INPUT DATA

    activite_par_titre = get_activites_data(csv_activites)
    activites_data = get_activites_annee(activite_par_titre, data_period)

    communes_par_titre = get_titres_data(csv_titres)
    titres_data = get_titres_annee(communes_par_titre, activites_data)

    entreprises_data = get_entreprises_data(csv_entreprises)

    full_data = get_simulation_full_data(titres_data, activites_data)

    rapports_annuels = select_reports(
        full_data,
        "rapport annuel de production d'or en Guyane"
        )
    assert (rapports_annuels.renseignements_orNet.notnull()).all()  # + 1 cas ajouté

    cleaned_data = clean_data(
        rapports_annuels
        )  # titres ayant des rapports annuels d'activité citant la production
    data = add_entreprises_data(cleaned_data, entreprises_data)

    # SIMULATION

    simulation_period = '2020'
    tax_benefit_system = FranceFiscaliteMiniereTaxBenefitSystem()
    current_parameters = tax_benefit_system.parameters(simulation_period)

    simulation = build_simulation(
        tax_benefit_system, simulation_period,
        data.titre_id, data.communes
        )

    simulation.set_input('surface_communale', data_period, data['surface_communale'])
    simulation.set_input('surface_totale', data_period, data['surface_totale'])
    simulation.set_input(
        'quantite_aurifere_kg',
        data_period,
        data['renseignements_orNet']
        )

    categories_entreprises_enum = get_categories_entreprises(data)
    simulation.set_input('categorie', data_period, categories_entreprises_enum)

    rapports_trimestriels = select_reports(
        full_data,
        "rapport trimestriel d'exploitation d'or en Guyane"
        )
    assert (
        rapports_trimestriels.renseignements_environnement.notnull()
        ).all()  # + 1 cas ajouté
    renseignements_environnement_annuels = calculate_renseignements_environnement_annuels(  # noqa: E501
        data.titre_id,
        rapports_trimestriels
        )
    simulation.set_input(
        'investissement',
        data_period,
        renseignements_environnement_annuels
        )

    rdm_tarif_aurifere = current_parameters.redevances.departementales.aurifere
    rcm_tarif_aurifere = current_parameters.redevances.communales.aurifere

    redevance_departementale_des_mines_aurifere_kg = simulation.calculate(
        'redevance_departementale_des_mines_aurifere_kg',
        simulation_period
        )
    redevance_communale_des_mines_aurifere_kg = simulation.calculate(
        'redevance_communale_des_mines_aurifere_kg',
        simulation_period
        )

    print("🍏    redevance_departementale_des_mines_aurifere_kg")
    print(redevance_departementale_des_mines_aurifere_kg)

    taxe_tarif_pme = current_parameters.taxes.guyane.categories.pme
    taxe_tarif_autres_entreprises = current_parameters.taxes.guyane.categories.autre
    taxe_guyane = simulation.calculate('taxe_guyane', simulation_period)
    taxe_guyane_deduction = simulation.calculate(
        'taxe_guyane_deduction',
        simulation_period
        )

    # SIMULATION OUTPUT

    colonnes = [
        'titre_id', 'communes', 'commune_exploitation_principale'
        'nom_entreprise', 'adresse_entreprise', 'siren', 'categorie_entreprise',
        # Base des redevances :
        'substances', 'renseignements_orNet',  # TODO domaine ?
        'surface_communale', 'surface_totale'
        # Redevance départementale :
        'tarifs_rdm',
        'redevance_departementale_des_mines_aurifere_kg',
        # Redevance communale :
        'tarifs_rcm',
        'redevance_communale_des_mines_aurifere_kg',
        # Taxe minière sur l'or de Guyane :
        'taxe_tarif_pme',
        'taxe_tarif_autres',
        'investissement',  # investissement déduit = openfisca taxe_guyane_deduction
        'taxe_guyane',
        'drfip',
        'observation'
        ]

    resultat = pandas.DataFrame(data, columns = colonnes)
    nb_titres = len(data.titre_id)
    categories_entreprises_connues = data['categorie_entreprise'].isin(
        ['PME', 'ETI', 'GE']
        )

    resultat['titre_id'] = data.titre_id
    resultat['communes'] = data.communes
    resultat['commune_exploitation_principale'] = data.commune_exploitation_principale
    resultat['surface_communale'] = data['surface_communale']
    resultat['surface_totale'] = data['surface_totale']

    resultat['nom_entreprise'] = data.nom_entreprise
    resultat['adresse_entreprise'] = data.adresse_entreprise
    resultat['siren'] = data.siren.astype(int).astype(str)  # afin d'éviter xxx.0 et concaténer  # noqa: E501
    resultat['categorie_entreprise'] = data.categorie_entreprise

    # Base des redevances :
    resultat['renseignements_orNet'] = data["renseignements_orNet"]

    # Redevance départementale :
    resultat['tarifs_rdm'] = numpy.where(
        redevance_departementale_des_mines_aurifere_kg > 0,
        rdm_tarif_aurifere,
        ""
        )
    resultat[
        'redevance_departementale_des_mines_aurifere_kg'
        ] = redevance_departementale_des_mines_aurifere_kg
    # Redevance communale :
    resultat['tarifs_rcm'] = numpy.where(
        redevance_communale_des_mines_aurifere_kg > 0,
        rcm_tarif_aurifere,
        ""
        )
    resultat[
        'redevance_communale_des_mines_aurifere_kg'
        ] = redevance_communale_des_mines_aurifere_kg
    # Taxe minière sur l'or de Guyane :
    resultat['taxe_tarif_pme'] = numpy.where(
        data['categorie_entreprise'] == "PME", taxe_tarif_pme, None)
    resultat['taxe_tarif_autres'] = numpy.where(
        (data['categorie_entreprise'] == "ETI")
        + (data['categorie_entreprise'] == "GE"),
        taxe_tarif_autres_entreprises, None
        )
    resultat['investissement'] = taxe_guyane_deduction
    resultat['taxe_guyane'] = taxe_guyane
    # https://lannuaire.service-public.fr/guyane/guyane/dr_fip-97302-01 :
    resultat['drfip'] = numpy.full(
        nb_titres,
        "Direction régionale des finances publiques (DRFIP) - Guyane"
        )
    resultat['observation'] = numpy.where(
        ~categories_entreprises_connues,
        "catégorie d'entreprise déduite (PME)",
        ""
        )

    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # TODO Vérifier quels titres du fichier CSV en entrée
    # ne sont pas dans le rapport final.
    generate_matrice_drfip_guyane(
        resultat,
        data_period,
        timestamp
        )

    generate_matrice_annexe_drfip_guyane(
        resultat,
        data_period,
        timestamp
        )
