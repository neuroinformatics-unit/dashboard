// Fetchers for download numbers data and metrics

import { Config, Fetcher, Result } from '..';
import { CustomOctokit } from '../lib/octokit';
import { Repository } from '@octokit/graphql-schema';
import { queryRepoNames } from './fetcher_utils';

export interface PePyResult {
  id: string;
  total_downloads: number;
  versions: string[];
  downloads: {
    [date: string]: {
      [version: string]: number;
    };
  };
  download_collapsed: {
    [date: string]: number;
  };
  download_monthly: number,
  download_weekly: number,
  download_daily: number,
}

const fetchDownloads = async (projectName: string) => {
  let retries = 2;
  // PePy API has a rate limit of 10 requests per minute
  let sleep_time = 70_000;
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  while (retries > 0) {
    try {
      const response = await fetch(`https://api.pepy.tech/api/v2/projects/${projectName}`, {
        headers: {
          'X-Api-Key': process.env.PEPY_API_KEY!,
        }
      });

      if (!response.ok && response.status === 404) {
        console.error(`Project ${projectName} not found on PePy`);
        return null;
      }

      if (!response.ok && response.status === 429) {
        console.error(`Error fetching download data for project ${projectName}: ${response.statusText}`);
        console.error(`Retrying in ${sleep_time}ms`);
        retries--;
        await sleep(sleep_time);
      }

      return await response.json() as PePyResult;
    } catch (error) {
      console.error(`Error fetching download data for project ${projectName}:`, error);
      console.error(`Retrying in ${sleep_time}ms`);
      retries--;
      await sleep(sleep_time);
    }
  }

  return null;
};

const queryProjectsForRepositories = async (repositories: Repository[]) => {
  const projectResults = [];

  for (const repo of repositories) {
    const projectData = await fetchDownloads(repo.name);
    if (projectData) {
      projectResults.push({repoName: repo.name, data: projectData as PePyResult});
    }
  }

  return projectResults;
};

const processDownloadNumbers = (projectResult: PePyResult) => {
  const currentDate = new Date();
  // Download results begin on previous day, so subtract 1 day
  currentDate.setDate(currentDate.getDate() - 1);
  const endDateMonth = new Date(new Date().setMonth(currentDate.getMonth() - 1));
  const endDateWeek = new Date(new Date().setDate(currentDate.getDate() - 7));

  projectResult.download_collapsed = {};

  Object.keys(projectResult.downloads).map((date) => {
    projectResult.download_collapsed[date] = Object.values(projectResult.downloads[date]).reduce((a, b) => a + b, 0);
  });

  projectResult.download_monthly = Object.keys(projectResult.download_collapsed).filter(
      (date) => new Date(date) > endDateMonth).reduce(
        (a, b) => a + projectResult.download_collapsed[b], 0);

  projectResult.download_weekly = Object.keys(projectResult.download_collapsed).filter(
    (date) => new Date(date) > endDateWeek).reduce(
      (a, b) => a + projectResult.download_collapsed[b], 0);

  projectResult.download_daily = projectResult.download_collapsed[currentDate.toISOString().split('T')[0]];
}

export const addDownloadsPePy: Fetcher = async (result: Result, octokit: CustomOctokit, config: Config) => {
  const repos = await queryRepoNames(octokit, config);
  const output = await queryProjectsForRepositories(repos);

  output.forEach((project) => {
    processDownloadNumbers(project.data);
    result.repositories[project.repoName].totalDownloadCount = project.data.total_downloads;
    result.repositories[project.repoName].monthlyDownloadCount = project.data.download_monthly;
    result.repositories[project.repoName].weeklyDownloadCount = project.data.download_weekly;
    result.repositories[project.repoName].dailyDownloadCount = project.data.download_daily;
  });

  return result;
};
