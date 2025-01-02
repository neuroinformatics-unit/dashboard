import fs from 'fs';
import os from 'os';
import path from 'path';
import * as https from 'node:https';
import { Config, Result } from '../index';
import { CustomOctokit } from '../lib/octokit';
import { queryRepoNames } from './fetcher_utils';

import { Database } from 'duckdb-async';

async function downloadParquetFile(url: string, outputPath: string) {
    return new Promise((resolve, reject) => {
        const file = fs.createWriteStream(outputPath);
        https.get(url, (response) => {
            if (response.statusCode !== 200) {
                reject(new Error(`Failed to get '${url}' (${response.statusCode})`));
                return;
            }
            response.pipe(file);
            file.on('finish', () => {
                file.close(resolve);
            });
        }).on('error', (err) => {
            fs.unlink(outputPath, () => reject(err));
        });
    });
}

export const addCondaData = async (result: Result, octokit: CustomOctokit, config: Config, startYear: number=2018) => {
    const repos = await queryRepoNames(octokit, config);
    const baseDir = path.join(os.homedir(), '.dashboard');

    const packages = repos.map((repo) => {return repo.name });

    const legacyPackagesMap = new Map<string, string>();
    if (config.organization === 'brainglobe') {
        const legacyPackages = JSON.parse(fs.readFileSync(path.resolve('brainglobe_legacy.json'), 'utf-8'));
        Object.entries(legacyPackages).forEach(([key, value]) => {
            if (typeof value === 'string') {
                legacyPackagesMap.set(key, value);
            }
        })

        packages.push(...legacyPackagesMap.keys());
    }

    if (!fs.existsSync(baseDir)) {
        fs.mkdirSync(baseDir);
    }

    let currYear = new Date().getFullYear();
    let lastMonth = 1;

    for (let i = startYear; i <= currYear; i++) {
        for (let j = 1; j <= 12; j++) {
            const fileName = path.join(baseDir, `${i}-${String(j).padStart(2, '0')}.parquet`);

            if (!fs.existsSync(fileName)) {
                const url = `https://anaconda-package-data.s3.amazonaws.com/conda/monthly/${i}/${i}-${String(j).padStart(2, '0')}.parquet`;

                // Check if the URL for the given month exists (status code 2xx)
                // The updates can take some time to be available, so there's
                // no easy way to know which month to stop at.
                const checkURLReq = await new Promise((resolve, reject) => {
                    fetch(url, {
                        method: "HEAD"
                    }).then(response => {
                        resolve(response.status.toString()[0] === "2")
                    }).catch(error => {
                        reject(false)
                    })
                })

                // If the URL does not exist, assume that there are no more
                // files to download and break the loop
                if (!checkURLReq) {
                    lastMonth = j > 1 ? j - 1 : 12;
                    // Make sure we break out of the outer loop as well
                    // Update teh current year to the last year we downloaded
                    currYear = i;
                    break;
                } else {
                    await downloadParquetFile(url, fileName);
                }
            }
        }
    }

    const db = await Database.create( `:memory:` );
    const formattedString = packages.map((pkg) => `'${pkg}'`).join(',');

    const totalDownloads = await db.all(`SELECT pkg_name, SUM(counts)::INTEGER AS total FROM '${baseDir}/*.parquet' WHERE pkg_name IN (${formattedString}) GROUP BY pkg_name`);

    if (lastMonth == 12) {
        currYear -= 1;
    }

    const lastMonthDownloads = await db.all(`SELECT pkg_name, SUM(counts)::INTEGER AS total FROM '${baseDir}/${currYear}-${String(lastMonth).padStart(2, '0')}.parquet' WHERE pkg_name IN (${formattedString}) GROUP BY pkg_name`);

    totalDownloads.forEach((row) => {
        if (legacyPackagesMap.has(row.pkg_name)) {
            row.pkg_name = legacyPackagesMap.get(row.pkg_name);
        }

        if ( !result.repositories[row.pkg_name].condaTotalDownloads ) {
            result.repositories[row.pkg_name].condaTotalDownloads = row.total;
        } else {
            result.repositories[row.pkg_name].condaTotalDownloads += row.total;
        }
    })

    lastMonthDownloads.forEach((row) => {
        if (legacyPackagesMap.has(row.pkg_name)) {
            row.pkg_name = legacyPackagesMap.get(row.pkg_name);
        }

        if (!result.repositories[row.pkg_name].condaMonthlyDownloads) {
            result.repositories[row.pkg_name].condaMonthlyDownloads = row.total;
        } else {
            result.repositories[row.pkg_name].condaMonthlyDownloads += row.total;
        }
    })

    return result;
};
