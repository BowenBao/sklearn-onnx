# SPDX-License-Identifier: Apache-2.0

# coding: utf-8
"""
Benchmark of onnxruntime on SVM.
"""
# Authors: Xavier Dupré (benchmark)
import warnings
from io import BytesIO
from time import perf_counter as time

import numpy as np
from numpy.random import rand
from numpy.testing import assert_almost_equal
import matplotlib.pyplot as plt
import pandas
from sklearn import config_context
from sklearn.svm import SVR
from sklearn.utils._testing import ignore_warnings
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
from onnxruntime import InferenceSession


##############################
# Implementations to benchmark.
##############################

def fcts_model(X, y, kernel):
    "SVR."
    rf = SVR(kernel=kernel)
    rf.fit(X, y)

    initial_types = [('X', FloatTensorType([None, X.shape[1]]))]
    onx = convert_sklearn(rf, initial_types=initial_types)
    f = BytesIO()
    f.write(onx.SerializeToString())
    content = f.getvalue()
    sess = InferenceSession(content)
    outputs = [o.name for o in sess.get_outputs()]

    def predict_skl_predict(X, model=rf):
        return rf.predict(X)

    def predict_onnxrt_predict(X, sess=sess):
        return sess.run(outputs[:1], {'X': X})[0]

    return {'predict': (
        predict_skl_predict,
        predict_onnxrt_predict,
    )}


##############################
# Benchmarks
##############################

def allow_configuration(**kwargs):
    return True


def bench(n_obs, n_features, kernels,
          methods, repeat=10, verbose=False):
    res = []
    for nfeat in n_features:

        ntrain = 1000
        X_train = np.empty((ntrain, nfeat)).astype(np.float32)
        X_train[:, :] = rand(ntrain, nfeat)[:, :]
        eps = rand(ntrain) - 0.5
        y_train = X_train.sum(axis=1) + eps

        for kernel in kernels:
            fcts = fcts_model(X_train, y_train, kernel)

            for n in n_obs:
                for method in methods:

                    fct1, fct2 = fcts[method]

                    if not allow_configuration(n=n, nfeat=nfeat,
                                               kernel=kernel):
                        continue

                    obs = dict(n_obs=n, nfeat=nfeat, kernel=kernel)

                    # creates different inputs to avoid caching in any ways
                    Xs = []
                    for r in range(repeat):
                        x = np.empty((n, nfeat))
                        x[:, :] = rand(n, nfeat)[:, :]
                        Xs.append(x.astype(np.float32))

                    # measures the baseline
                    with config_context(assume_finite=True):
                        st = time()
                        repeated = 0
                        for X in Xs:
                            p1 = fct1(X)
                            repeated += 1
                            if time() - st >= 1:
                                break  # stops if longer than a second
                        end = time()
                        obs["time_skl"] = (end - st) / repeated

                    # measures the new implementation
                    st = time()
                    r2 = 0
                    for X in Xs:
                        p2 = fct2(X)
                        r2 += 1
                        if r2 >= repeated:
                            break
                    end = time()
                    obs["time_ort"] = (end - st) / repeated

                    # final
                    res.append(obs)
                    if verbose and (len(res) % 1 == 0 or n >= 10000):
                        print("bench", len(res), ":", obs)

                    # checks that both produce the same outputs
                    if n <= 10000:
                        if len(p1.shape) == 1 and len(p2.shape) == 2:
                            p2 = p2.ravel()
                        try:
                            assert_almost_equal(
                                p1.ravel(), p2.ravel(), decimal=3)
                        except AssertionError as e:
                            warnings.warn(str(e))
    return res


##############################
# Plots.
##############################

def plot_results(df, verbose=False):
    nrows = max(len(set(df.n_obs)), 2)
    ncols = 2
    fig, ax = plt.subplots(nrows, ncols,
                           figsize=(ncols * 4, nrows * 4))
    pos = 0
    row = 0
    for n_obs in sorted(set(df.n_obs)):
        a = ax[row, pos]
        if row == ax.shape[0] - 1:
            a.set_xlabel("N features", fontsize='x-small')
        if pos == 0:
            a.set_ylabel(
                "Time (s) n_obs={}".format(n_obs), fontsize='x-small')

        for color, kernel in zip('brgyc', sorted(set(df.kernel))):
            subset = df[(df.kernel == kernel)]
            if subset.shape[0] == 0:
                continue
            subset = subset.sort_values("nfeat")
            if verbose:
                print(subset)

            label = "skl %s" % kernel
            subset.plot(x="nfeat", y="time_skl", label=label, ax=a,
                        logx=True, logy=True, c=color, style='--', lw=5)
            label = "ort %s" % kernel
            subset.plot(x="nfeat", y="time_ort", label=label, ax=a,
                        logx=True, logy=True, c=color, lw=3)

        a.legend(loc=0, fontsize='x-small')
        if row == 0:
            pass  # a.set_title("n_jobs={}".format(n_jobs), fontsize='x-small')
        row += 1

    plt.suptitle("Benchmark for SVR sklearn/onnxruntime", fontsize=16)


@ignore_warnings(category=FutureWarning)
def run_bench(repeat=100, verbose=False):
    n_obs = [1, 10, 100, 1000, 10000, 100000]
    methods = ['predict']
    n_features = [10, 50]
    kernels = ["linear", "poly", "rbf", "sigmoid"]

    start = time()
    results = bench(n_obs, n_features, kernels,
                    methods, repeat=repeat, verbose=verbose)
    end = time()

    results_df = pandas.DataFrame(results)
    print("Total time = %0.3f sec\n" % (end - start))

    # plot the results
    plot_results(results_df, verbose=verbose)
    return results_df


if __name__ == '__main__':
    from datetime import datetime
    import sklearn
    import numpy
    import onnx
    import onnxruntime
    import skl2onnx
    df = pandas.DataFrame([
        {"name": "date", "version": str(datetime.now())},
        {"name": "numpy", "version": numpy.__version__},
        {"name": "scikit-learn", "version": sklearn.__version__},
        {"name": "onnx", "version": onnx.__version__},
        {"name": "onnxruntime", "version": onnxruntime.__version__},
        {"name": "skl2onnx", "version": skl2onnx.__version__},
    ])
    df.to_csv("bench_plot_onnxruntime_svm_reg.time.csv", index=False)
    print(df)
    df = run_bench(verbose=True)
    df.to_csv("bench_plot_onnxruntime_svm_reg.csv", index=False)
    # plt.show()
