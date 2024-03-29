import os, time, hubspot, datetime
import regex as re
import pandas as pd
from dotenv import load_dotenv
from map_industries import make_ind_dict, make_tag_dict
from write import create_property, update_property
from write import update_company, batch_update_company
from write import batch_update_contact

load_dotenv()


# DIRCCTORIES
DBDIR = "C:/Users/galon/Sputnik ATX Team Dropbox/Programming Datasets"
RAW_DIR = os.path.join(DBDIR, "tables", "raw")
CLEAN_DIR = os.path.join(DBDIR, "tables", "clean")
IND_DIR = os.path.join(CLEAN_DIR, "industry_mapping")


# INPATHS
START_HERF_PATH = os.path.join(CLEAN_DIR, "scraped_data", "crunchbase", "cb_inv_overview_scraped.csv")
VC_PATH = os.path.join(RAW_DIR, "hs", "vc_list_export.csv")
VC_INDUSTRY_COLS = os.path.join(RAW_DIR, "hs", "vc_industry_columns.csv")
STARTPATH = os.path.join(CLEAN_DIR, "scraped_data", "crunchbase", "cb_startups_main.csv")
TX_ANGEL_HS_INPATH = os.path.join(RAW_DIR, 'hs', 'tx_angel_export.csv')
TX_ANGEL_RAW_INPATH = os.path.join(RAW_DIR, 'misc_source', 'tx_angel_contacts.csv')
MERGED_VC_PATH = os.path.join(CLEAN_DIR, 'scraped_data', 'crunchbase', 'cb_vc_main_merged.csv')
INVOV_INPATH = os.path.join(CLEAN_DIR,"scraped_data","crunchbase", "cb_inv_overview_scraped.csv")


# OUTPATHS
MAPPING_OUTPATH = os.path.join(IND_DIR, "cb_starts_mapped.csv")



"""
#### Below is a reference for the internal property names in HubSpot ####

Portfolio Industries: pf_inds
Portfolio Focus: top5_inds
Portfolio Main Interest: top1_inds
Investing Tags: pf_tags
Top 5 Tags: top5_tags
Top Tag: top1_tags
Record ID: id
Company name: name
Investor Tags: inv_tags
Texas Angel Industries: tx_angel_inds
Texas Angel Tags: tx_angel_tags
Preferred Stages: stage



#### Rate limits for companies and contacts must be below a certain threshold ####

Set the rate limit for companies at no more than 10
Set the rate limit for contacts at no more than 10

"""


def counter(item_list):

    """Counts items from a list"""
    
    count_dict = {}
    for item in item_list:
        if item in count_dict:
            count_dict[item] += 1
        else:
            count_dict[item] = 1
    return count_dict



def count_stage(l):

    """Lambda function for coutning the stages that an investor has been involved in."""
    
    new_l = []
    
    for string in l:

        if 'unknown' in string.lower():
            continue
        if 'from' in string.lower():
            string = string.lower().split('from')[0].strip()
            string = ' '.join([s.capitalize() for s in string.split()])
        elif 'discover' in string.lower().strip():
            string = string.lower().split('discover')[0].strip()
            string =  ' '.join([s.capitalize() for s in string.split()])
        new_l.append(string)
    return set(new_l)

def get_stages(csv_inpath):

    """Gets the stages in a company after a certain date"""

    df = pd.read_csv(csv_inpath)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] > datetime.datetime(2019, 12, 31)]
    df = df.groupby(["id"]).agg(
        {
            "stage": lambda x: list(x)
        }
    )
    df["Record ID"] = df.index.astype("int64")
    return df

def rank_top5(count_dict, column):

    """Finds the top 5 most used words from a list of words"""
    
    data = {column: list(count_dict.keys()), 'count': list(count_dict.values())}
    df = pd.DataFrame.from_dict(data)
    df.sort_values(['count'], ascending=False,inplace=True)
    top5 = df[column].values[0:5]

    
    return ''.join([f';{t}' for t in top5])

def rank_top1(count_dict, column):

    """Finds the most used word in a list of words"""

    data = {column: list(count_dict.keys()), 'count': list(count_dict.values())}
    df = pd.DataFrame.from_dict(data)
    df.sort_values(['count'], ascending=False,inplace=True)
    if len(df) > 0:

        return df[column].values[0]


def explode_df(csv_inpath, industry_column, split_on):

    """Cleans the dataframe and explodes on the industry"""

    df = pd.read_csv(csv_inpath).rename(columns={industry_column: "industries"})
    df["ref"] = df["industries"]
    df = df[~df["industries"].isnull()]
    df["industries"] = df["industries"].apply(lambda x: re.split(split_on, str(x)))
    df = df.explode("industries")
    df["industries"] = df["industries"].apply(lambda x: re.sub(r"&", "and", str(x)))
    df["industries"] = df["industries"].apply(lambda x: x.lower().strip())

    return df


def map_groups(exploded_df, new_col, map_dict):

    """Takes the exploded dataframe and groups the industries based on a mapping dictionary"""

    merge_df = exploded_df.copy(deep=True)
    merge_df[new_col] = ""
    exploded_df.reset_index(inplace=True)

    for key, value in map_dict.items():

        map_df = pd.DataFrame({key: value})
        map_df[key] = map_df[key].apply(lambda x: x.lower())
        matches = exploded_df.merge(
            map_df, how="left", left_on="industries", right_on=key
        )
        merge_df.loc[
            matches[~matches[key].isnull()]["index"].values, new_col
        ] += f";{key}"
    return merge_df


def aggregate(df, dictionary):

    """Aggregates the dataframe based on columns specificied in the dictionary parameter"""

    return df.groupby(df.index).agg(dictionary)


def mental_health(df):

    """Creates a mental health industry based on a company description mentioning mental health"""

    df['description'] = df['description'].apply(lambda x: x.lower())
    df.loc[
        df["description"].str.contains("mental health"), "pf_inds"
    ] += ";Mental Health"

    return df


def map_subindustries(ind_list):

    """If a broad industry and a subcategory of that indsustry are listed together, this function removes the more general industry"""

    ind_tuples = [
        ("Mental Health", "Health"),
        ("Payment Card Industry (PCI)", "FinTech"),
        ("FinTech", "Financial Services"),
        ("InsurTech", "Insurance"),
        ("HealthTech", "Health"),
        ("Enterprise Software", "Software"),
        ("Streaming Platform", "Arts and Entertainment"),
        ("Transportation", "Automotive"),
        ("Pharmaceuticals", "Health"),
        ("3D Printing", "Manufacturing"),
        ("E-Commerce", "Commerce"),
        ("Multimedia and Graphics Software", "Software"),
        ("AgTech", "Agriculture and Farming"),
    ]

    for i in ind_tuples:
        if i[0] in ind_list and i[1] in ind_list:
            ind_list = [ind for ind in ind_list if ind != i[1]]
    return ";".join(ind_list)


def make_property_dict(df, column):

    """Makes a dictionary from the created dataframe to use for API put calls"""

    df = df[~df[column].isnull()]
    print(df)

    return [
        {
            "id": str(k),
            "properties": {
                column: re.sub(r' ','_', str(df[column].values[n])).lower(),
            },
        }
        for n, k in enumerate(df["Record ID"].values)
    ]


def rate_limit_company(rate, dict_list):

    """Rate limiter for put calls to the HubSpot CRM API. 
    Recommend 100 for the rate limit.
    """


    end = False

    for i, e in enumerate(dict_list):

        if end == True:
            batch_update_company(dict_list[i::])
            break
        else:
            if i // rate == i / rate:
                if len(dict_list) - (i) < rate:
                    end = True
                    print(f"Arrived at the end! Updating last batch.")
                    continue
                else:
                    print()
                    batch_update_company(dict_list[i : i + rate])
                    print(f"Just updated batches {i}-{i+rate} \n Sleeping shhhh...")
                    time.sleep(10)


def startup_ind_main():

    """Collects the set of industries that we categorize for a startup."""


    df = map_groups(
        explode_df(STARTPATH, "industries", ","), "pf_inds", make_ind_dict()
    ).drop(['Unnamed: 0'],axis=1)
    df = aggregate(
        df,
        {
            "pf_inds": lambda x: ("".join(str(s.strip()) for s in set(x))).strip(),
            "href": lambda x: list(set(x))[0],
            "name": lambda x: list(set(x))[0],
            "description": lambda x: list(set(x))[0],
            "ref": lambda x: list(set(x))[0],
        },
    )
    df = mental_health(df)
    df["pf_inds"] = df["pf_inds"].apply(lambda x: x.split(";"))
    df["pf_inds"] = df["pf_inds"].apply(lambda x: map_subindustries(x))
    df = pd.read_csv(START_HERF_PATH).merge(
        df, how="left", left_on="startup_href", right_on="href"
    )

    return df[~df["pf_inds"].isnull()]


def startup_tag_main():


    """Collects the set of tags that we categorize for a startup."""

    df = map_groups(
        explode_df(STARTPATH, "industries", ","), "pf_tags", make_tag_dict()
    )
    df = aggregate(
        df,
        {
            "pf_tags": lambda x: ("".join(str(s.strip()) for s in set(x))).strip(),
            "href": lambda x: list(set(x))[0],
            "name": lambda x: list(set(x))[0],
            "description": lambda x: list(set(x))[0],
            "ref": lambda x: list(set(x))[0],
        },
    )

    df["pf_tags"] = df["pf_tags"].apply(lambda x: x.split(";"))
    df = pd.read_csv(START_HERF_PATH).merge(
        df, how="left", left_on="startup_href", right_on="href"
    )

    return df[~df["pf_tags"].isnull()]

def tx_angel_ind_main():

    """Collects the set of all industries that exist for an investor in the TX Angel csv."""


    df = map_groups(explode_df(TX_ANGEL_RAW_INPATH, "Preferred Industry", ","), "tx_angel_inds", make_ind_dict())
    df = aggregate(
        df,
        {
            "tx_angel_inds": lambda x: ("".join(str(s.strip()) for s in set(x))).strip(),
            "Description": lambda x: list(set(x))[0],
            "Investor Name": lambda x: list(set(x))[0],
        },
    )
    df["tx_angel_inds"] = df["tx_angel_inds"].apply(lambda x: x.split(";"))
    df["tx_angel_inds"] = df["tx_angel_inds"].apply(lambda x: map_subindustries(x))
    hs_df = pd.read_csv(TX_ANGEL_HS_INPATH).rename(columns={'Record ID - Contact': 'id'})
    hs_df['name'] = hs_df['First Name'] + ' ' + hs_df['Last Name']
    df = df.merge(hs_df, how='right', left_on=['Investor Name', 'Description'],right_on=['name', 'About'])
    df['tx_angel_inds'] = df['tx_angel_inds'].astype('str')

    return df[df['tx_angel_inds'].str.contains(';')]


def tx_angel_tag_main():

    """Collects the set of all tags that exist for an investor in the TX Angel csv."""

    df = map_groups(explode_df(TX_ANGEL_RAW_INPATH, "Preferred Industry", ","), "tx_angel_tags", make_tag_dict())
    df = aggregate(
        df,
        {
            "tx_angel_tags": lambda x: ("".join(str(s.strip()) for s in set(x))).strip(),
            "Description": lambda x: list(set(x))[0],
            "Investor Name": lambda x: list(set(x))[0],
        },
    )
    df["tx_angel_tags"] = df["tx_angel_tags"].apply(lambda x: x.split(";"))
    df["tx_angel_tags"] = df["tx_angel_tags"].apply(lambda x: map_subindustries(x))
    hs_df = pd.read_csv(TX_ANGEL_HS_INPATH).rename(columns={'Record ID - Contact': 'id'})
    hs_df['name'] = hs_df['First Name'] + ' ' + hs_df['Last Name']
    df = df.merge(hs_df, how='right', left_on=['Investor Name', 'Description'],right_on=['name', 'About'])
    df['tx_angel_tags'] = df['tx_angel_tags'].astype('str')

    return df[df['tx_angel_tags'].str.contains(';')]



def inv_stages_main():

    """Collects the set of all stage types that an investor has participated in."""
    
    df = get_stages(INVOV_INPATH)
    df['stage'] = df['stage'].apply(lambda x: f";{';'.join(count_stage(x))}")
    return df[df['stage'].str.contains(';')]


def get_top1_industries(df, internal_label):

    """Gets the most used industry for a given investor's portfolio."""

    df['counts'] = df[internal_label].apply(lambda x: counter(x))
    df['top1_inds'] = df['counts'].apply(lambda x: rank_top1(x, 'industry'))
    df['Record ID'] = df.index

    return df


def get_top5_industries(df, internal_label):

    """Gets the top 5 most used industries for a given investor's portfolio."""
    
    df['counts'] = df[internal_label].apply(lambda x: counter(x))
    df['top5_inds'] = df['counts'].apply(lambda x: rank_top5(x, 'industry'))
    df['Record ID'] = df.index
    
    return df

def get_top1_tags(df, internal_label):

    """Gets the most used tag for a given investor's portfolio."""

    df['counts'] = df[internal_label].apply(lambda x: counter(x))
    df['top1_tags'] = df['counts'].apply(lambda x: rank_top1(x, 'tag'))
    df['Record ID'] = df.index

    return df

def get_top5_tags(df, internal_label):

    """Gets the top 5 most used tags for a given investor's portfolio."""
    
    df['counts'] = df[internal_label].apply(lambda x: counter(x))
    df['top5_tags'] = df['counts'].apply(lambda x: rank_top5(x, 'tag'))
    df['Record ID'] = df.index
    
    return df


def make_options_dataframe(mapping_function, name, groupby):

    """Outputs final dataframe with information that will be inputted to the CRM.

    mapping_function: this should be a function with 'main' in the method's name; output is a dataframe

    name: this is a column of the mapped industry, which will also be the internal hubspot name

    groupby: this is the record id column, which was different across projects and why it's included as an arugment

    """

    df = (
        mapping_function
        .groupby([groupby])
        .agg(
            {
                name: lambda x: f"{';'.join(set(sum(x, [])))}",
            }
        )
    )
    df['Record ID'] = df.index
    return df

def make_options_dict(df, column):

    """Creates a dictionary from the dataframe that was created in make_options_dataframe for the API put call."""


    df = df[~df[column].isnull()]
    tags = "".join(list(df[column].values))
    labels = list(set(tags.split(";")))
    labels.pop(0)
    values = [re.sub(r" ", "_", label).lower() for label in labels]

    return [
        {"label": label, "value": values[n], "displayOrder": n, "hidden": False}
        for n, label in enumerate(labels)
    ]


if __name__ == "__main__":

    ### STEP 1 ###
    # If your property does not already include every value in the current dictionary, create a new one or update the current one. Keep the first object mapped to make_industry_options; will always be true.
    """

                            ################## Example ######################


                            df = tx_angel_tag_main().groupby(['id']).agg({'tx_angel_tags': lambda x: [s for s in (''.join(x).split(';')) if len(s) > 0]})
                            df = make_options_dataframe(df, 'tx_angel_tags', 'id')
                            options_dict_list = make_options_dict(df, 'tx_angel_tags')
                            print(options_dict_list)
                            create_property(
                                        'tx_angel_tags',
                                        'Preferred Tags (TX Angels)',
                                        'enumeration',
                                        'checkbox',
                                        'contactinformation',
                                        options_dict_list,
                                        1,
                                        False,
                                        False,
                                        True,
                                        'contact'
                                )

                            #################################################
    """


    ### Step 2 ###
    # Update the comapnies, but USE THE RATE LIMITER. If you don't the update will fail
    # IF YOU MAKE TOO MANY REQUESTS HUBSPOT WILL BE BIG MAD, SO BE CAREFUL.
    """

                            #################### Example ####################

                                df = startup_ind_main().groupby(['id']).agg({'pf_inds': lambda x: [s for s in (''.join(x).split(';')) if len(s) > 0]})

                                df_list = [industry_options_dataframe(startup_ind_main(), 'pf_inds', 'id'), get_top5_industries(df, 'pf_inds'), get_top1_industries(df, 'pf_inds')]
                                col_list = ['pf_inds', 'top5_inds', 'top1_inds']

                                for i, df in enumerate(df_list):

                                    prop_dict_list = make_property_dict(df, col_list[i])

                                    print(prop_dict_list)
                                    rate_limit_dict(100, prop_dict_list)

                            #################################################
    """


    

