import os
import math
import numpy as np
from multiprocessing import Pool, Process, Queue, Manager
import multiprocessing
from gensim.corpora import Dictionary
manager = multiprocessing.Manager()
q_to_store = manager.Queue()

def get_docu_feature(text_data, storage_path, is_save):

    text_content = []
    for content in text_data.values():
        text_content.append(content["content"])
    dct = Dictionary(text_content)

    dfs = np.zeros(len(dct), dtype=[("term", "a30"), ("df", "f4")])
    for i in range(len(dct)):
        dfs[i]["term"] = dct.__getitem__(i)
        dfs[i]["df"] = dct.dfs[i]
        
    idfs = np.zeros(len(dct), dtype=[("term", "a30"), ("idf", "f4")])
    idfs["term"] = dfs["term"]
    idfs["idf"] = np.log(len(text_data)/(dfs["df"]+1.0))

    if is_save == True:
        np.save(os.path.join(storage_path, "dfs.npy"), dfs)
        np.save(os.path.join(storage_path, "idfs.npy"), idfs)

    return idfs

def get_term_feature(id_, cont, idfs):
    
    tf = np.zeros([1, idfs.size], dtype=[("id", "a250"), ("term", "a30"), ("tf", "f4"), ("lv_tf", "f4"), ("length", "f4"), ("norm", "f4")])
    
    tf["id"] = id_
    tf["term"] = idfs["term"]
    tf["length"] = len(cont)
    for term in cont:
        tf["tf"][tf["term"] == term.encode()] += 1
    tf["lv_tf"] = np.log(tf["tf"]) + 1
    tf["lv_tf"][np.isinf(tf["lv_tf"])] = 0
    
    q_to_store.put(tf)
    #return tf

def tfidf_creation(text_data, idfs, storage_path, is_save):
    
    tfs = np.zeros([1, idfs.size], dtype=[("id", "a250"), ("term", "a30"), ("tf", "f4"), ("lv_tf", "f4"), ("length", "f4"), ("norm", "f4")])

    # def update_tfs(tf):
    #     nonlocal tfs
    #     tfs = np.concatenate((tfs, tf), 0)

    pool = multiprocessing.Pool(multiprocessing.cpu_count())
    for id_, cont in text_data.items():
        pool.apply_async(get_term_feature, args=(id_, cont["content"], idfs))# , callback= update_tfs)
    pool.close()
    pool.join()

    while not q_to_store.empty():
        tf = q_to_store.get()
        tfs = np.concatenate((tfs, tf), 0)
        
    print(tfs.shape)
    tfs = np.delete(tfs, 0, 0)
    print(tfs.shape)
    min_length = np.mean(tfs["length"], 0)[0] - 3*np.std(tfs["length"], 0)[0]
    max_length = np.mean(tfs["length"], 0)[0] + 3*np.std(tfs["length"], 0)[0]
    tfs["norm"] = 1.0 / (1 + np.exp(- 6 * (tfs["length"] - min_length) / (max_length - min_length)))
    print("b")
    tf_idfs = np.zeros(tfs.shape, dtype=[("id", "a250"),("term", "a30"), ("tf_idf", "f4"), ("norm", "f4")])
    for i in range(tf_idfs.shape[0]):
        tf_idfs[i]["tf_idf"] = np.multiply(tfs[i]["lv_tf"], idfs["idf"])
    # tf_idfs["tf_idf"] = np.multiply(tfs["lv_tf"], idfs["idf"])
    print("c")
    tf_idfs["id"] = tfs["id"]
    tf_idfs["term"] = tfs["term"]
    tf_idfs["norm"] = tfs["norm"]

    if is_save == True:
        np.save(os.path.join(storage_path, "tfs.npy"), tfs)
        np.save(os.path.join(storage_path, "tf_idfs.npy"), tf_idfs)

    return tf_idfs

def update_tfidf_feature(text_data, added_files, deleted_files, modified_files, storage_path):
    
    tf_idfs = np.load(os.path.join(storage_path, "tf_idfs.npy"))
    if len(deleted_files) + len(added_files) + len(modified_files) == 0:
        return tf_idfs

    tfs = np.load(os.path.join(storage_path, "tfs.npy"))
    dfs = np.load(os.path.join(storage_path, "dfs.npy"))
    idfs = np.load(os.path.join(storage_path, "idfs.npy"))
    
    min_length = np.mean(tfs["length"], 0)[0] - 3*np.std(tfs["length"], 0)[0]
    max_length = np.mean(tfs["length"], 0)[0] + 3*np.std(tfs["length"], 0)[0]
    
    if not len(deleted_files) - len(added_files) == 0:
        original_num = len(text_data) + len(deleted_files) - len(added_files)
        if not len(text_data)==0:
            update_val = math.log(len(text_data)) - math.log(original_num)
            idfs["idf"] += update_val

    count = np.zeros(dfs.size)
    temp_count = np.zeros(tfs.size)
    temp_count = tfs["tf"]
    temp_count[temp_count>0] = 1
    count = np.sum(temp_count, 0)

    # for deleted files, delete the corresponding row in the tf array and change df
    for code_file in deleted_files:
        if not np.where(tfs["id"] == code_file.encode())[0].size == 0:
            tfs = np.delete(tfs, np.where(tfs["id"] == code_file.encode())[0][0], 0)
            tf_idfs = np.delete(tf_idfs, np.where(tf_idfs["id"] == code_file.encode())[0][0], 0)
    temp_count = tfs["tf"]
    temp_count[temp_count>0] = 1
    count = count - np.sum(temp_count, 0)
    dfs["df"] = dfs["df"] - count
    
    # for modified files, update tf value, df value, and add terms
    for code_file in modified_files:

        code_file = code_file[0]
        for i in range(tfs.shape[0]):
            if tfs[i]["id"][0] == code_file.encode():
                tfs[i]["length"] = len(text_data[code_file]["content"])
                tfs[i]["norm"] = 1.0 / (1 + np.exp(- 6 *(tfs[i]["length"] - min_length) / (max_length - min_length)))
                
                # store new tf value
                tf_temp = np.zeros(dfs.size, dtype=[("term", "a30"), ("tf", "f4")])
                tf_temp["term"] = dfs["term"]
                for term in text_data[code_file]["content"]:
                    if not dfs[dfs["term"]==term.encode()].size == 0:
                        # store tf value for old term
                        tf_temp["tf"][tf_temp["term"] == term.encode()] += 1
                    else:
                        # add new term to tf array
                        temp = np.zeros([tfs.shape[0], 1], dtype=[("id", "a250"), ("term", "a30"), ("tf", "f4"), ("lv_tf", "f4"), ("length", "f4"), ("norm", "f4")])
                        temp["term"] = term.encode()
                        tfs = np.concatenate((tfs, temp), 1)
                        
                        # add new term to tf_idf array
                        temp = np.zeros([tf_idfs.shape[0], 1], dtype=[("id", "a250"),("term", "a30"), ("tf_idf", "f4"), ("norm", "f4")])
                        temp["term"] = term.encode()
                        tf_idfs = np.concatenate((tf_idfs, temp), 1)
                        
                        # add new term to df, idf array
                        dfs = np.concatenate((dfs, np.asarray([(term.encode(), 0)], dtype=[("term", "a30"), ("df", "f4")])))
                        idfs = np.concatenate((idfs, np.asarray([(term.encode(), 0)], dtype=[("term", "a30"), ("idf", "f4")])))
                        
                        tf_temp = np.concatenate((tf_temp, np.asarray([(term.encode(), 0)], dtype=[("term", "a30"), ("tf", "f4")])))
                        tf_temp["tf"][tf_temp["term"] == term.encode()] += 1

                # update df, idf, tf        
                for term in dfs["term"]:
                    if (tf_temp[dfs["term"] == term]["tf"] == 0) and not (tfs[i][dfs["term"] == term]["tf"] == 0):
                        update_val = dfs[dfs["term"] == term]["df"] - 1
                        dfs[dfs["term"] == term] = np.asarray([(term, update_val)], dtype=[("term", "a30"), ("df", "f4")])
                        idfs["idf"][idfs["term"] == term] = np.log(len(text_data)/(dfs["df"][dfs["term"] == term]+1))
                    elif not (tf_temp[dfs["term"] == term]["tf"] == 0) and (tfs[i][dfs["term"] == term]["tf"] == 0):
                        update_val = dfs[dfs["term"] == term]["df"] + 1
                        dfs[dfs["term"] == term] = np.asarray([(term, update_val)], dtype=[("term", "a30"), ("df", "f4")])
                        idfs["idf"][idfs["term"] == term] = np.log(len(text_data)/(dfs["df"][dfs["term"] == term]+1))
                    tfs[i]["tf"][tf_temp["term"] == term] = tf_temp["tf"][tf_temp["term"] == term]

                tfs[i]["lv_tf"] = np.log(tfs[i]["tf"]) + 1
                tfs[i]["lv_tf"][np.isinf(tfs[i]["lv_tf"])] = 0
                tf_idfs[i]["tf_idf"] = np.multiply(tfs[i]["lv_tf"], idfs["idf"])
                break

    # for the added file, add a new row to array firstly, and then update tf value, df value, and add terms 
    for code_file in added_files:
        code_file = code_file[0]

        # add a new row to tf
        temp = np.zeros([1, tfs.shape[1]], dtype=[("id", "a250"), ("term", "a30"), ("tf", "f4"), ("lv_tf", "f4"), ("length", "f4"), ("norm", "f4")])
        temp["id"] = code_file.encode()
        if not tfs["term"].size == 0:
            temp["term"] = tfs["term"][0]
        try: 
            temp["length"] = len(text_data[code_file]["content"])
        except:
            continue
        temp["norm"] = 1.0 / (1 + np.exp(- 6 *(temp["length"] - min_length) / (max_length - min_length)))
        tfs = np.concatenate((tfs, temp), 0)

        # add a new row to tfidf
        temp = np.zeros([1, tf_idfs.shape[1]], dtype=[("id", "a250"),("term", "a30"), ("tf_idf", "f4"), ("norm", "f4")])
        temp["id"] = code_file.encode()
        if not tf_idfs["term"].size == 0:
            temp["term"] = tf_idfs["term"][0]
        temp["norm"] = tfs[-1]["norm"]
        tf_idfs = np.concatenate((tf_idfs, temp), 0)

        # store new tf value
        tf_temp = np.zeros(dfs.size, dtype=[("term", "a30"), ("tf", "f4")])
        tf_temp["term"] = dfs["term"]

        for term in text_data[code_file]["content"]:
            if not dfs[dfs["term"]==term.encode()].size == 0:
                # store tf for old term in the new row
                tf_temp["tf"][tf_temp["term"] == term.encode()] += 1
            else:
                # add new term to tf array
                temp = np.zeros([tfs.shape[0], 1], dtype=[("id", "a250"), ("term", "a30"), ("tf", "f4"), ("lv_tf", "f4"), ("length", "f4"), ("norm", "f4")])
                temp["term"] = term.encode()
                tfs = np.concatenate((tfs, temp), 1)
                
                # add new term to tf_idf array
                temp = np.zeros([tf_idfs.shape[0], 1], dtype=[("id", "a250"),("term", "a30"), ("tf_idf", "f4"), ("norm", "f4")])
                temp["term"] = term.encode()
                tf_idfs = np.concatenate((tf_idfs, temp), 1)
                
                # add new term to df, idf array
                dfs = np.concatenate((dfs, np.asarray([(term.encode(), 0)], dtype=[("term", "a30"), ("df", "f4")])))
                idfs = np.concatenate((idfs, np.asarray([(term.encode(), 0)], dtype=[("term", "a30"), ("idf", "f4")])))
                
                tf_temp = np.concatenate((tf_temp, np.asarray([(term.encode(), 0)], dtype=[("term", "a30"), ("tf", "f4")])))
                tf_temp["tf"][tf_temp["term"] == term.encode()] += 1
        
        # update df, idf, tf   
        for term in dfs["term"]:
            if tf_temp[tf_temp["term"] == term]["tf"] > 0:
                update_val = dfs[dfs["term"] == term]["df"] + 1
                dfs[dfs["term"] == term] = np.asarray([(term, update_val)], dtype=[("term", "a30"), ("df", "f4")])
                idfs["idf"][idfs["term"] == term] = np.log(len(text_data)/(dfs["df"][dfs["term"] == term]+1))
            tfs[-1]["tf"][tf_temp["term"] == term] = tf_temp["tf"][tf_temp["term"] == term]

        tfs[-1]["lv_tf"] = np.log(tfs[-1]["tf"]) + 1
        tfs[-1]["lv_tf"][np.isinf(tfs[-1]["lv_tf"])] = 0
        tf_idfs[-1]["tf_idf"] = np.multiply(tfs[-1]["lv_tf"], idfs["idf"])

    # delete terms whose df==0
    tfs = np.delete(tfs, np.where(dfs["df"] == 0), 1)
    tf_idfs = np.delete(tf_idfs, np.where(dfs["df"] == 0), 1)
    idfs = np.delete(idfs, np.where(dfs["df"] == 0), 0)
    dfs = np.delete(dfs, np.where(dfs["df"] == 0), 0)

    # make id and norm same in each row
    for i in range(tfs.shape[0]):
        tfs[i]["id"] = tfs[i]["id"][0]
        tfs[i]["norm"] = tfs[i]["norm"][0]
        tf_idfs[i]["id"] = tf_idfs[i]["id"][0]
        tf_idfs[i]["norm"] = tf_idfs[i]["norm"][0]

    # if min or max length changes, update the norm value in whole array
    if not min_length == (np.mean(tfs["length"], 0)[0] - 3*np.std(tfs["length"], 0)[0]) or not max_length == (np.mean(tfs["length"], 0)[0] + 3*np.std(tfs["length"], 0)[0]):
        min_length = np.mean(tfs["length"], 0)[0] - 3*np.std(tfs["length"], 0)[0]
        max_length = np.mean(tfs["length"], 0)[0] + 3*np.std(tfs["length"], 0)[0]
        tfs["norm"] = 1.0 / (1 + np.exp(- 6 * (tfs["length"] - min_length) / (max_length - min_length)))

    np.save(os.path.join(storage_path, "tfs.npy"), tfs)
    np.save(os.path.join(storage_path, "dfs.npy"), dfs)
    np.save(os.path.join(storage_path, "idfs.npy"), idfs)
    np.save(os.path.join(storage_path, "tf_idfs.npy"), tf_idfs)

    return tf_idfs
