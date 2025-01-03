// Fetchers for repository data and metrics

import { Organization, Repository } from '@octokit/graphql-schema';
import { Fetcher } from '..';
import { RepositoryResult } from '../../../types';
import excludedRepos from '../../excluded_repos.json';

export const addRepositoriesToResult: Fetcher = async (
  result,
  octokit,
  config,
) => {
  const organization = await octokit.graphql.paginate<{
    organization: Organization;
  }>(
    `
  query ($cursor: String, $organization: String!) {
    organization(login:$organization) {
      repositories(privacy:PUBLIC, first:100, isFork:false, isArchived:false, after: $cursor)
      {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          name
          nameWithOwner
          forkCount
          stargazerCount
          isFork
          isArchived
          hasIssuesEnabled
          hasProjectsEnabled
          hasDiscussionsEnabled
          projects {
            totalCount
          }
          projectsV2 {
            totalCount
          }
          discussions {
            totalCount
          }
          licenseInfo {
            name
          }
          watchers {
            totalCount
          }
          repositoryTopics(first: 20) {
            nodes {
              topic {
                name
              }
            }
          }
        }
      }
    }
  }
  `,
    {
      organization: config.organization,
    },
  );

  const filteredRepos = organization.organization.repositories.nodes!.filter(
    (repo) =>
      (!(repo?.isArchived && !config.includeArchived) ||
      !(repo.isFork && !config.includeForks)) &&
      !(excludedRepos.includes(repo!.name) ||
      repo!.name.startsWith("slides-") ||
      repo!.name.startsWith("course-")),
  ) as Repository[];

  // Just in case the filteredRepos is not stably ordered
  const contributorsMap = new Map<string, number>();

  let contributorsWaiting = []
  for (const repo of filteredRepos) {
    let currResult = await octokit.request(`GET /repos/${config.organization}/${repo.name}/stats/contributors`, {
      owner: config.organization,
      repo: repo.name,
      headers: {
        'X-GitHub-Api-Version': '2022-11-28'
      }
    })

    if (currResult.status == 200) {
      contributorsMap.set(repo.name, currResult.data.length);
    }
    else if (currResult.status == 202) {
      console.log(`Contributors data for ${repo.name} is not ready yet`);
      contributorsWaiting.push(repo)
    } else {
      console.error(`Error fetching contributors data for ${repo.name}: ${currResult.status}`);
    }
  }

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  while (contributorsWaiting.length > 0) {
    console.log(`Waiting for contributors data from ${contributorsWaiting.length} repositories to be ready`);
    await sleep(60000);
    const stillWaiting: Repository[] = []
    for (const repo of contributorsWaiting) {
      let currResult = await octokit.request(`GET /repos/${config.organization}/${repo.name}/stats/contributors`, {
        owner: config.organization,
        repo: repo.name,
        headers: {
          'X-GitHub-Api-Version': '2022-11-28'
        }
      })

      if (currResult.status === 200) {
        contributorsMap.set(repo.name, currResult.data.length);
      } else if (currResult.status === 202) {
        console.log(`Contributors data for ${repo.name} is not ready yet`);
        stillWaiting.push(repo)
      } else {
        console.error(`Error fetching contributors data for ${repo.name}: ${currResult.status}`);
      }
    }

    contributorsWaiting = stillWaiting
  }

  return {
    ...result,
    repositories: filteredRepos.reduce(
      (acc, repo) => {
        return {
          ...acc,
          [repo.name]: {
            repositoryName: repo.name,
            repoNameWithOwner: repo.nameWithOwner,
            licenseName: repo.licenseInfo?.name || 'No License',
            topics: repo.repositoryTopics.nodes?.map(
              (node) => node?.topic.name,
            ),
            forksCount: repo.forkCount,
            watchersCount: repo.watchers.totalCount,
            starsCount: repo.stargazerCount,
            contributorsCount: contributorsMap.get(repo.name) || 0,
            issuesEnabled: repo.hasIssuesEnabled,
            projectsEnabled: repo.hasProjectsEnabled,
            discussionsEnabled: repo.hasDiscussionsEnabled,
            collaboratorsCount: repo.collaborators?.totalCount || 0,
            projectsCount: repo.projects.totalCount,
            projectsV2Count: repo.projectsV2.totalCount,
          } as RepositoryResult,
        };
      },
      {} as Record<string, RepositoryResult>,
    ),
  };
};
